"""
trend_best_of.py

Raccolta per il "best of" (Sala, Streaming, Festival) con uno score di trend.

Legge dal DB del warehouse (articles_dim, categories_dim, articles_categories,
fact_ga4_daily) e, per Sala e Streaming, dalle visite Wikipedia (external_trend.py).
I dati GA4 arrivano fin dove ha caricato l'ETL: lo script stampa l'ultimo giorno
disponibile (`make refresh` per aggiornare).

UNITA': il "contenuto" e' il titolo dell'opera, non il singolo articolo. Gli articoli
della stessa sezione che citano lo stesso titolo tra apici (es. 'Se domani non torno':
recensione + trailer + intervista) si sommano in un'unica riga. Un articolo senza
titolo tra apici resta una riga a se'.

SEZIONI (un articolo sta in una sola, priorita' Sala > Streaming > Festival):
  Sala      = categoria in-sala (26) e figlie
  Streaming = live-streaming-on-demand (25048) e figlie (+ Serie TV con --with-serie-tv)
  Festival  = festival-di-cinema (20) e figlie

SCORE DI TREND (0-100)
  Sala e Streaming -> ESTERNO, non dipende dal nostro pubblico. Percentili dentro la
    sezione (winsorizzati 5-95) di
      volume    35%  Wikipedia: log(1 + visite della voce nella finestra)
      momentum  35%  Wikipedia: log2((visite/gg ultimi R + k) / (visite/gg R precedenti + k)),
                     k = mediana delle medie giornaliere della sezione (smorza i numeri piccoli)
      TMDB      30%  log(1 + popolarita' TMDB), solo con TMDB_API_KEY (globale, senza storico)
    Una componente mancante vale 0.5 (neutra): un titolo con una sola fonte non esce a
    0 o a 100 solo perche' ha meno componenti degli altri. I titoli senza nessuna fonte
    esterna restano sotto quelli con score, ordinati per score editoriale.
  Festival -> SCORE EDITORIALE (article_scoring.py, lo stesso del report settimanale),
    perche' i festival piccoli non hanno segnale esterno e il nostro pubblico e'
    rappresentativo del pubblico dei festival. Per il gruppo si prende l'articolo migliore.
    Calcolato sugli utenti attivi giornalieri sommati nella finestra (approssimazione:
    gli utenti unici di periodo non sono sommabili) e confrontato con tutti gli articoli
    del sito nella stessa finestra.

Uso (dalla radice del progetto, con il Postgres su):
    .venv/Scripts/python.exe scripts/trend_best_of.py
    .venv/Scripts/python.exe scripts/trend_best_of.py --start 2026-10-05 --end 2026-11-02
    .venv/Scripts/python.exe scripts/trend_best_of.py --days 14 --recent-days 3 --max-age-days 30
    .venv/Scripts/python.exe scripts/trend_best_of.py --no-external   # senza chiamare Wikipedia
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ga4_client"))
sys.path.insert(0, str(ROOT / "scripts"))

import external_trend  # noqa: E402
import signal_sources  # noqa: E402
from article_scoring import score_articles  # noqa: E402
from data_access.db import query_df  # noqa: E402
from midreport_client import is_excluded_title  # noqa: E402  (esclusioni editoriali)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SECTION_ROOTS = {"Sala": [26], "Streaming": [25048], "Festival": [20]}
SERIE_TV_ROOTS = [29923, 33785, 33786, 36480, 33788, 50587, 33787, 33791]
SECTION_PRIORITY = ["Sala", "Streaming", "Festival"]
EXTERNAL_SECTIONS = ("Sala", "Streaming")

EXTERNAL_WEIGHTS = {"volume": 0.35, "momentum": 0.35, "tmdb": 0.30}
LOWER_PERCENTILE, UPPER_PERCENTILE = 0.05, 0.95
MOMENTUM_BAND = 0.5  # |log2| oltre cui si parla di crescita/calo (~ +-41%)

CONTENT_TYPE_BY_SLUG = {
    "review": "Recensione", "in-sala": "Recensione", "trailers": "Trailer",
    "interviews": "Intervista", "interviews-interviews": "Intervista",
    "latest-news": "News", "focus-italia": "News",
}
_QUOTED_TITLE = re.compile(r"‘(.+?)’(?=[\s:,.;!?)\-–—]|$)")


# ---------------------------------------------------------------- raccolta dati


def latest_metric_date() -> dt.date:
    return query_df("SELECT max(metric_date) AS d FROM fact_ga4_daily")["d"].iloc[0]


def fetch_articles(end: dt.date, max_age_days: int, with_serie_tv: bool) -> pd.DataFrame:
    """Articoli delle tre sezioni pubblicati negli ultimi `max_age_days` giorni."""
    roots = {s: list(r) for s, r in SECTION_ROOTS.items()}
    if with_serie_tv:
        roots["Streaming"] += SERIE_TV_ROOTS
    values = ",".join(f"({c},'{s}')" for s, cs in roots.items() for c in cs)
    sql = f"""
        WITH RECURSIVE tree AS (
            SELECT v.category_id, v.section FROM (VALUES {values}) AS v(category_id, section)
          UNION
            SELECT c.category_id, t.section
            FROM tree t JOIN categories_dim c ON c.parent_id = t.category_id
        )
        SELECT a.article_id, a.title, a.link,
               (a.published_at AT TIME ZONE 'Europe/Rome')::date AS pub_date,
               array_agg(DISTINCT t.section) AS sections
        FROM articles_dim a
        JOIN articles_categories ac ON ac.article_id = a.article_id
        JOIN tree t ON t.category_id = ac.category_id
        WHERE a.status = 'publish'
          AND (a.published_at AT TIME ZONE 'Europe/Rome')::date BETWEEN %(lo)s AND %(hi)s
        GROUP BY a.article_id, a.title, a.link, a.published_at
    """
    df = query_df(sql, {"lo": end - dt.timedelta(days=max_age_days), "hi": end})
    df["section"] = df["sections"].map(lambda ss: next(s for s in SECTION_PRIORITY if s in ss))
    df["title"] = df["title"].map(lambda t: html.unescape(t) if isinstance(t, str) else "")
    df["pub_date"] = pd.to_datetime(df["pub_date"])
    return df[~df["title"].map(is_excluded_title)].drop(columns="sections").reset_index(drop=True)


def fetch_content_types(article_ids: list[int]) -> dict[int, set[str]]:
    df = query_df(
        "SELECT ac.article_id, cd.slug FROM articles_categories ac "
        "JOIN categories_dim cd ON cd.category_id = ac.category_id WHERE ac.article_id = ANY(%(ids)s)",
        {"ids": article_ids},
    )
    out: dict[int, set[str]] = {}
    for article_id, slug in zip(df["article_id"], df["slug"]):
        if slug in CONTENT_TYPE_BY_SLUG:
            out.setdefault(article_id, set()).add(CONTENT_TYPE_BY_SLUG[slug])
    return out


def fetch_daily_all(start: dt.date, end: dt.date) -> pd.DataFrame:
    """Tutte le metriche GA4 per (articolo, giorno), per tutto il sito."""
    sql = """
        SELECT article_id, metric_date,
               sum(metric_value) FILTER (WHERE metric_name = 'screen_page_views')      AS views,
               sum(metric_value) FILTER (WHERE metric_name = 'active_users')           AS active_users,
               sum(metric_value) FILTER (WHERE metric_name = 'sessions')               AS sessions,
               sum(metric_value) FILTER (WHERE metric_name = 'engaged_sessions')       AS engaged_sessions,
               sum(metric_value) FILTER (WHERE metric_name = 'user_engagement_duration') AS engagement_s,
               sum(metric_value) FILTER (WHERE metric_name = 'average_session_duration') AS avg_session_s
        FROM fact_ga4_daily WHERE metric_date BETWEEN %(s)s AND %(e)s
        GROUP BY article_id, metric_date
    """
    df = query_df(sql, {"s": start, "e": end}).fillna(0.0)
    df["metric_date"] = pd.to_datetime(df["metric_date"])
    return df


def editorial_scores(daily_all: pd.DataFrame) -> pd.Series:
    """Score editoriale (article_scoring.py) per articolo, sulla finestra intera."""
    d = daily_all.assign(dur_x_sess=daily_all["avg_session_s"] * daily_all["sessions"])
    g = d.groupby("article_id").agg(
        activeUsers=("active_users", "sum"), screenPageViews=("views", "sum"), sessions=("sessions", "sum"),
        engagedSessions=("engaged_sessions", "sum"), userEngagementDuration=("engagement_s", "sum"),
        dur_x_sess=("dur_x_sess", "sum"),
    ).reset_index()
    sess = g["sessions"].replace(0, np.nan)
    g["engagementRate"] = (g["engagedSessions"] / sess).fillna(0)
    g["bounceRate"] = 1 - g["engagementRate"]
    g["averageSessionDuration"] = (g["dur_x_sess"] / sess).fillna(0)
    scored = score_articles(g.drop(columns="dur_x_sess"))
    return scored.set_index("article_id")["editorial_score"]


# ------------------------------------------------------------------ raggruppo


def title_key(title: str) -> tuple[str | None, str | None]:
    """(chiave normalizzata, titolo leggibile) dal primo titolo tra apici, o (None, None)."""
    # Il titolo d'opera sta all'inizio dell'articolo ("‘Titolo’ – sottotitolo"). Un titolo
    # tra apici in mezzo a una frase (rassegne: "… da ‘Peccato’ a ‘Backrooms’") non e' il
    # soggetto dell'articolo e non va usato per raggruppare ne' per cercare segnali.
    m = _QUOTED_TITLE.search(title)
    if not m or title[:m.start()].strip():
        return None, None
    label = m.group(1).strip()
    norm = unicodedata.normalize("NFKD", label.casefold())
    norm = "".join(ch for ch in norm if not unicodedata.combining(ch))
    norm = re.sub(r"[^a-z0-9]+", " ", norm).strip()
    return (norm or None), label


def attach_clusters(articles: pd.DataFrame) -> pd.DataFrame:
    keys = articles["title"].map(title_key)
    articles = articles.assign(norm=[k[0] for k in keys], label=[k[1] for k in keys])
    singleton = articles["norm"].isna()
    articles["cluster_id"] = np.where(
        singleton, "art:" + articles["article_id"].astype(str), articles["section"] + "|" + articles["norm"].fillna(""))
    articles["cluster_label"] = np.where(singleton, articles["title"], articles["label"])
    return articles


# ----------------------------------------------------------------------- score


def _winsor_rank(s: pd.Series) -> pd.Series:
    if len(s) == 1:
        return pd.Series(0.5, index=s.index)
    clipped = s.clip(s.quantile(LOWER_PERCENTILE), s.quantile(UPPER_PERCENTILE))
    return clipped.rank(method="average", pct=True)


def _split(series: pd.Series, end: dt.date, r: int) -> tuple[float, float, float]:
    """(totale finestra, ultimi r giorni, r giorni precedenti) di una serie giornaliera."""
    end_ts = pd.Timestamp(end)
    recent_from = end_ts - dt.timedelta(days=r - 1)
    prior_from = end_ts - dt.timedelta(days=2 * r - 1)
    rec = series[series.index >= recent_from].sum()
    pri = series[(series.index >= prior_from) & (series.index < recent_from)].sum()
    return float(series.sum()), float(rec), float(pri)


def _momentum(recent: pd.Series, prior: pd.Series, r: int, k: float) -> pd.Series:
    return np.log2((recent / r + k) / (prior / r + k))


def build_clusters(articles: pd.DataFrame, daily_all: pd.DataFrame, types: dict[int, set[str]],
                   start: dt.date, end: dt.date, r: int, min_views: int, use_external: bool,
                   sources: tuple = ()) -> pd.DataFrame:
    editorial = editorial_scores(daily_all)
    ours = daily_all[daily_all["article_id"].isin(articles["article_id"])].merge(
        articles[["article_id", "cluster_id"]], on="article_id")
    per_cluster_day = ours.groupby(["cluster_id", "metric_date"])["views"].sum()
    rows = {}
    for cid, s in per_cluster_day.groupby(level=0):
        rows[cid] = _split(s.droplevel(0), end, r)
    our = pd.DataFrame.from_dict(rows, orient="index", columns=["views", "views_recent", "views_prior"])

    arts = articles.assign(
        types=articles["article_id"].map(lambda a: types.get(a, set())),
        art_views=articles["article_id"].map(daily_all.groupby("article_id")["views"].sum()).fillna(0),
        editorial=articles["article_id"].map(editorial),
    ).sort_values("art_views", ascending=False)
    info = arts.groupby("cluster_id").agg(
        section=("section", "first"), titolo=("cluster_label", "first"), n_articoli=("article_id", "nunique"),
        prima_pubblicazione=("pub_date", "min"), ultima_pubblicazione=("pub_date", "max"),
        link_principale=("link", "first"), editorial_score=("editorial", "max"),
        tipi=("types", lambda ss: ", ".join(sorted(set().union(*ss)))),
    )
    c = info.join(our, how="left").fillna({"views": 0, "views_recent": 0, "views_prior": 0})
    if c.empty:
        return c
    # Soglia: decide solo chi entra nelle schede in classifica. I segnali si cercano per tutti.
    c["in_classifica"] = c["views"] >= min_views
    c["cercato"] = [_looks_like_work(cid, t) for cid, t in zip(c.index, c["titolo"])]
    window_days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1

    # Nostre views: solo contesto (confronto "fuori vs da noi"), non entra nello score.
    k_ours = max(1.0, float((c["views"] / window_days).median()))
    c["momentum_nostro"] = _momentum(c["views_recent"], c["views_prior"], r, k_ours)

    for col in ("wiki_pagina", "wiki_views", "wiki_recent", "wiki_prior", "momentum", "r_volume", "r_momentum",
                "tmdb_titolo", "tmdb_pop", "tmdb_pop_prev", "r_tmdb"):
        c[col] = None if col in ("wiki_pagina", "tmdb_titolo") else np.nan
    signal_sources.ensure_columns(c)
    for col, _, _, is_pop in signal_sources.COLUMNS:
        if is_pop:
            c[f"r_{col}"] = np.nan
    c["trend_score"] = np.nan
    c["fonte_score"] = ""
    c.loc[c["section"] == "Festival", "trend_score"] = c["editorial_score"]
    c.loc[c["section"] == "Festival", "fonte_score"] = "Score editoriale"

    if use_external:
        _add_external(c, start, end, r, sources)
        signal_sources.add_ranks(c, _winsor_rank)
    c.loc[(c["section"].isin(EXTERNAL_SECTIONS)) & c["trend_score"].isna(), "fonte_score"] = \
        "Nessun dato esterno (solo editoriale)"
    c["trend_score"] = c["trend_score"].round(1)

    def phase(row) -> str:
        mom = row["momentum"] if pd.notna(row["momentum"]) else row["momentum_nostro"]
        if row["prima_pubblicazione"] >= pd.Timestamp(end) - dt.timedelta(days=r - 1):
            return "Novita'"
        return "In crescita" if mom >= MOMENTUM_BAND else "In calo" if mom <= -MOMENTUM_BAND else "Stabile"

    c["fase"] = c.apply(phase, axis=1)
    c["has_trend"] = c["trend_score"].notna()
    c["sort_key"] = c["trend_score"].fillna(-1)
    c = c.sort_values(["section", "has_trend", "sort_key", "editorial_score"],
                      ascending=[True, False, False, False])
    return c.drop(columns=["has_trend", "sort_key"]).reset_index()


def _looks_like_work(cluster_id: str, title: str) -> bool:
    """True se il gruppo e' un titolo d'opera da cercare fuori.

    Titolo tra apici: si'. Articolo senza apici: solo se il titolo e' corto e non ha i
    segni di una rassegna o di un programma (due punti, un anno, oltre 45 caratteri).
    """
    if not cluster_id.startswith("art:"):
        return True
    return len(title) <= 45 and ":" not in title and not re.search(r"\b20\d{2}\b", title)


def _add_external(c: pd.DataFrame, start: dt.date, end: dt.date, r: int, sources: tuple = ()) -> None:
    """Segnali esterni per TUTTE le sezioni: Wikipedia sempre, TMDB se c'e' la chiave.

    Ogni fonte e' una colonna a se': un contenuto puo' averne alcune e non altre. Lo score
    composito si calcola solo per Sala e Streaming.
    """
    min_year = end.year - 1
    key = external_trend.tmdb_key()
    if not key:
        print("TMDB_API_KEY non impostata: salto TMDB (solo Wikipedia).")
    today = dt.date.today()
    found = []
    tmdb_items: dict = {}
    todo = c[c["cercato"]]
    print(f"Cerco i segnali esterni per {len(todo)} titoli (le risposte gia' note sono in cache)...", flush=True)
    for i, (cid, row) in enumerate(todo.iterrows(), start=1):
        if i % 40 == 0:
            print(f"  {i}/{len(todo)}", flush=True)
            external_trend.save_cache()
        page = external_trend.find_page(row["titolo"], min_year)
        if page:
            w, rec, pri = _split(external_trend.pageviews(page, start, end), end, r)
            c.loc[cid, ["wiki_pagina", "wiki_views", "wiki_recent", "wiki_prior"]] = [
                f"{page['lang']}: {page['title']}", w, rec, pri]
        if key:
            item = external_trend.find_tmdb(row["titolo"], min_year, key)
            if item:
                found.append(item)
                tmdb_items[cid] = item
                prev = external_trend.previous_popularity(item, today, r)
                c.loc[cid, ["tmdb_titolo", "tmdb_pop", "tmdb_pop_prev"]] = [
                    f"{item['media_type']}: {item['title']} ({item['year']})", item["popularity"],
                    np.nan if prev is None else prev]
    external_trend.save_cache()
    external_trend.save_snapshot(found, today)

    if sources:  # altre fonti: ognuna in colonne proprie, nessun composito
        ctx = signal_sources.Ctx(start=start, end=end, r=r, min_year=min_year, today=today,
                                 tmdb_key=key, tmdb_items=tmdb_items)
        signal_sources.run(c, ctx, list(sources))

    window_days = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    for section in SECTION_PRIORITY:
        sec = c["section"].eq(section)
        mw = sec & c["wiki_views"].notna()
        mt = sec & c["tmdb_pop"].notna()
        if mw.any():
            k = max(1.0, float((c.loc[mw, "wiki_views"] / window_days).median()))
            c.loc[mw, "momentum"] = _momentum(c.loc[mw, "wiki_recent"], c.loc[mw, "wiki_prior"], r, k)
            c.loc[mw, "r_volume"] = _winsor_rank(np.log1p(c.loc[mw, "wiki_views"]))
            c.loc[mw, "r_momentum"] = _winsor_rank(c.loc[mw, "momentum"])
        if mt.any():
            c.loc[mt, "r_tmdb"] = _winsor_rank(np.log1p(c.loc[mt, "tmdb_pop"]))
        if section not in EXTERNAL_SECTIONS:
            continue  # Festival: i segnali restano colonne separate, il trend e' lo score editoriale
        # Media pesata su tutte e tre le componenti; quella mancante vale 0.5 (neutra),
        # cosi' i titoli con una sola fonte non escono a 0 o a 100 solo perche' hanno meno
        # componenti degli altri.
        parts = {"r_volume": EXTERNAL_WEIGHTS["volume"], "r_momentum": EXTERNAL_WEIGHTS["momentum"],
                 "r_tmdb": EXTERNAL_WEIGHTS["tmdb"]}
        sub = c[sec]
        score = 100 * sum(sub[col].fillna(0.5) * w for col, w in parts.items()) / sum(parts.values())
        has = sub[list(parts)].notna().any(axis=1)
        c.loc[sub.index[has], "trend_score"] = score[has]
        both = sub["r_volume"].notna() & sub["r_tmdb"].notna()
        label = np.where(both, "Esterno (Wikipedia + TMDB)",
                         np.where(sub["r_volume"].notna(), "Esterno (Wikipedia)", "Esterno (TMDB)"))
        c.loc[sub.index[has], "fonte_score"] = pd.Series(label, index=sub.index)[has]


# ---------------------------------------------------------------------- Excel

CLUSTER_COLUMNS = {
    "pos": "Pos.", "titolo": "Titolo", "tipi": "Tipi di articolo", "n_articoli": "N. articoli",
    "trend_score": "Trend score", "fonte_score": "Fonte score", "fase": "Fase",
    "wiki_pagina": "Voce Wikipedia", "wiki_views": "Wiki views finestra", "wiki_recent": "Wiki views ultimi R gg",
    "wiki_prior": "Wiki views R gg precedenti", "momentum": "Momentum esterno (log2)",
    "r_volume": "Rank volume esterno", "r_momentum": "Rank momentum esterno",
    "tmdb_titolo": "Voce TMDB", "tmdb_pop": "TMDB popolarita'", "tmdb_pop_prev": "TMDB popolarita' R gg fa",
    "r_tmdb": "Rank TMDB",
    "editorial_score": "Score editoriale", "views": "Nostre views finestra",
    "views_recent": "Nostre views ultimi R gg", "views_prior": "Nostre views R gg precedenti",
    "momentum_nostro": "Nostro momentum (log2)", "prima_pubblicazione": "Prima pubblicazione",
    "ultima_pubblicazione": "Ultima pubblicazione", "link_principale": "Link articolo principale",
}


def _style(ws, df: pd.DataFrame, freeze: str = "C2",
           wide: tuple = ("Titolo", "Link articolo principale")) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    ws.freeze_panes = freeze
    for i, col in enumerate(df.columns, start=1):
        cell = ws.cell(row=1, column=i)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F3A5F")
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        width = 52 if col in wide else \
            30 if col in ("Voce Wikipedia", "Voce TMDB", "Fonte score", "Voce Trakt", "Video YouTube",
                          "Pagina Rotten Tomatoes") else max(11, min(22, len(col) + 2))
        ws.column_dimensions[get_column_letter(i)].width = width
        fmt = None
        if col.endswith("(0-100)"):
            fmt = "0.0"
        elif col.startswith("Google Trends") and "momentum" not in col:
            fmt = "0.000"
        elif "momentum" in col.lower() or col.startswith("Rank"):
            fmt = "0.00"
        elif col.startswith(("IMDb voti", "Trakt s", "Trakt v", "Trakt l", "Trakt c", "RT n.")):
            fmt = "#,##0"
        elif col in ("Trend score", "Score editoriale"):
            fmt = "0.0"
        elif "views" in col.lower():
            fmt = "#,##0"
        elif "pubblicazione" in col or col == "Data":
            fmt = "dd/mm/yyyy"
        if fmt:
            for r in range(2, ws.max_row + 1):
                ws.cell(row=r, column=i).number_format = fmt
    ws.row_dimensions[1].height = 45
    ws.auto_filter.ref = ws.dimensions


def write_excel(clusters: pd.DataFrame, articles: pd.DataFrame, daily_all: pd.DataFrame, path: Path,
                meta: dict, min_views: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    readme = pd.DataFrame({"Voce": list(meta), "Valore": [str(v) for v in meta.values()]})
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        readme.to_excel(xw, sheet_name="Leggimi", index=False)
        xw.sheets["Leggimi"].column_dimensions["A"].width = 30
        xw.sheets["Leggimi"].column_dimensions["B"].width = 130
        for section in SECTION_PRIORITY:
            g = clusters[(clusters["section"] == section) & clusters["in_classifica"]].copy()
            g.insert(0, "pos", range(1, len(g) + 1))
            sheet = g[list(CLUSTER_COLUMNS)].rename(columns=CLUSTER_COLUMNS)
            sheet.to_excel(xw, sheet_name=section, index=False)
            _style(xw.sheets[section], sheet)
        signals = signals_table(articles, clusters, daily_all)
        signals.to_excel(xw, sheet_name="Segnali", index=False)
        _style(xw.sheets["Segnali"], signals, freeze="D2", wide=("Titolo articolo", "Opera / gruppo", "Link"))
        cov = coverage_table(clusters, min_views)
        cov.to_excel(xw, sheet_name="Copertura", index=False)
        _style(xw.sheets["Copertura"], cov, freeze="C2", wide=())


def coverage_table(clusters: pd.DataFrame, min_views: int) -> pd.DataFrame:
    """Quanti contenuti hanno quale fonte esterna, per sezione e per perimetro."""
    rows = []
    perimeters = (("Tutti i contenuti", pd.Series(True, index=clusters.index)),
                  (f"In classifica (>= {min_views} nostre views)", clusters["in_classifica"]))
    for section in SECTION_PRIORITY:
        for name, mask in perimeters:
            g = clusters[(clusters["section"] == section) & mask]
            w, t = g["wiki_views"].notna(), g["tmdb_pop"].notna()
            any_src = w | t
            for pcol in signal_sources.PRESENCE.values():
                any_src = any_src | g[pcol].notna()
            rows.append({
                "Sezione": section, "Perimetro": name, "Contenuti (titoli)": len(g),
                "Articoli": int(g["n_articoli"].sum()),
                "Non cercati (non sembrano opere)": int((~g["cercato"]).sum()),
                "Cercati": int(g["cercato"].sum()),
                "Con Wikipedia": int(w.sum()), "Con TMDB": int(t.sum()), "Con entrambe": int((w & t).sum()),
                **{f"Con {name}": int(g[col].notna().sum()) for name, col in
                   (("IMDb", "imdb_votes"), ("Google Trends", "gt_ratio"), ("YouTube", "yt_views"),
                    ("Trakt", "trakt_watchers"), ("Rotten Tomatoes", "rt_critics"))},
                "Con almeno una fonte": int(any_src.sum()),
                "Cercati senza risultato": int((g["cercato"] & ~any_src).sum()),
                "% contenuti con almeno una fonte": round(100 * any_src.mean(), 1) if len(g) else np.nan,
                "Articoli con almeno una fonte": int(g.loc[any_src, "n_articoli"].sum()),
            })
    return pd.DataFrame(rows)


def signals_table(articles: pd.DataFrame, clusters: pd.DataFrame, daily_all: pd.DataFrame) -> pd.DataFrame:
    """Una riga per articolo, una colonna per fonte: nessun indicatore composito.

    I segnali esterni sono dell'opera (lo stesso valore per gli articoli dello stesso
    titolo); sono vuoti dove la fonte non ha niente. Gli score 0-100 sono percentili
    dentro la sezione, calcolati solo tra i titoli che hanno quel segnale.
    """
    cols = ["cluster_id", "cercato", "wiki_pagina", "wiki_views", "wiki_recent", "wiki_prior", "momentum",
            "r_volume", "r_momentum", "tmdb_titolo", "tmdb_pop", "tmdb_pop_prev", "r_tmdb", "views",
            "in_classifica"]
    new_cols = [col for col, *_ in signal_sources.COLUMNS]
    rank_cols = [f"r_{col}" for col, _, _, pop in signal_sources.COLUMNS if pop]
    det = articles.merge(clusters[cols + new_cols + rank_cols], on="cluster_id", how="left")
    det["art_views"] = det["article_id"].map(daily_all.groupby("article_id")["views"].sum()).fillna(0)
    det["editorial_articolo"] = det["article_id"].map(editorial_scores(daily_all))
    det["n_fonti"] = det[["wiki_views", "tmdb_pop"] + list(signal_sources.PRESENCE.values())].notna().sum(axis=1)
    det["cercato"] = det["cercato"].map({True: "Si'", False: "No (non sembra un'opera)"})
    for src, dst in (("r_volume", "score_wiki_volume"), ("r_momentum", "score_wiki_momentum"), ("r_tmdb", "score_tmdb")):
        det[dst] = (100 * det[src]).round(1)
    det = det.sort_values(["section", "n_fonti", "art_views"], ascending=[True, False, False])
    for col, _, _, pop in signal_sources.COLUMNS:
        if pop:
            det[f"score_{col}"] = (100 * det[f"r_{col}"]).round(1)
    base = ["section", "article_id", "title", "cluster_label", "pub_date", "cercato", "n_fonti",
            "wiki_pagina", "wiki_views", "wiki_recent", "wiki_prior", "momentum", "score_wiki_volume",
            "score_wiki_momentum", "tmdb_titolo", "tmdb_pop", "tmdb_pop_prev", "score_tmdb"]
    names = ["Sezione", "ID articolo", "Titolo articolo", "Opera / gruppo", "Data", "Cercato fuori",
             "N. fonti esterne", "Voce Wikipedia", "Wiki views finestra", "Wiki views ultimi R gg",
             "Wiki views R gg precedenti", "Wiki momentum (log2)", "Score Wikipedia volume (0-100)",
             "Score Wikipedia momentum (0-100)", "Voce TMDB", "TMDB popolarita'",
             "TMDB popolarita' R gg fa", "Score TMDB (0-100)"]
    # una fonte dopo l'altra: valori grezzi, poi lo score 0-100 della metrica di popolarita'
    for col, header, _, pop in signal_sources.COLUMNS:
        base.append(col)
        names.append(header)
        if pop:
            base.append(f"score_{col}")
            names.append(f"Score {header} (0-100)")
    base += ["art_views", "views", "editorial_articolo", "link"]
    names += ["Nostre views articolo", "Nostre views gruppo", "Score editoriale articolo", "Link"]
    out = det[base].copy()
    out.columns = names
    return out


# ------------------------------------------------------------------------ main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=dt.date.fromisoformat, help="primo giorno (default: end - days + 1)")
    ap.add_argument("--end", type=dt.date.fromisoformat, help="ultimo giorno (default: ultimo caricato nel DB)")
    ap.add_argument("--days", type=int, default=28, help="lunghezza finestra se manca --start (default 28)")
    ap.add_argument("--recent-days", type=int, default=7, help="R: giorni 'recenti' per il momentum (default 7)")
    ap.add_argument("--max-age-days", type=int, default=45, help="solo articoli pubblicati da meno di N giorni (default 45)")
    ap.add_argument("--min-views", type=int, default=30, help="nostre views minime nella finestra per entrare (default 30)")
    ap.add_argument("--with-serie-tv", action="store_true", help="aggiunge le serie TV alla sezione Streaming")
    ap.add_argument("--no-external", action="store_true", help="non interroga Wikipedia (Sala/Streaming senza score esterno)")
    ap.add_argument("--no-save-db", action="store_true",
                    help="non scrive i segnali in fact_article_signal (default: li scrive, in modo idempotente)")
    ap.add_argument("--sources", default=",".join(signal_sources.SOURCES),
                    help="altre fonti di popolarita', separate da virgola, tra: "
                         + ", ".join(signal_sources.SOURCES) + " (default tutte; '' = nessuna)")
    ap.add_argument("--top", type=int, default=10, help="righe per sezione nella stampa (default 10)")
    ap.add_argument("--output", type=Path, help="file xlsx (default output/best_of_trend_<start>_<end>.xlsx)")
    args = ap.parse_args()

    db_last = latest_metric_date()
    end = args.end or db_last
    start = args.start or end - dt.timedelta(days=args.days - 1)
    start = min(start, end - dt.timedelta(days=2 * args.recent_days - 1))
    print(f"Finestra {start} -> {end} (ultimo giorno GA4 nel DB: {db_last}); R={args.recent_days}")

    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    unknown = [s for s in sources if s not in signal_sources.SOURCES]
    if unknown:
        print(f"Fonti sconosciute: {unknown}. Valide: {list(signal_sources.SOURCES)}")
        return 2
    articles = fetch_articles(end, args.max_age_days, args.with_serie_tv)
    if articles.empty:
        print("Nessun articolo nelle sezioni per il periodo.")
        return 1
    articles = attach_clusters(articles)
    daily_all = fetch_daily_all(start, end)
    types = fetch_content_types(articles["article_id"].tolist())
    clusters = build_clusters(articles, daily_all, types, start, end, args.recent_days, args.min_views,
                              use_external=not args.no_external, sources=sources)
    if clusters.empty:
        print("Nessun contenuto trovato.")
        return 1

    meta = {
        "Finestra": f"{start} -> {end}", "Ultimo giorno GA4 nel DB": db_last,
        "Giorni recenti (R)": args.recent_days, "Eta' massima articoli (giorni)": args.max_age_days,
        "Soglia": f"almeno {args.min_views} nostre views nella finestra per entrare in elenco",
        "Unita'": "Titolo tra apici (articoli sullo stesso titolo sommati); altrimenti il singolo articolo",
        "Sezioni": "Sala = in-sala; Streaming = live-streaming-on-demand"
                   + (" + serie TV" if args.with_serie_tv else "") + "; Festival = festival-di-cinema. "
                   "Un articolo sta in una sola sezione (priorita' Sala > Streaming > Festival)",
        "Score Sala/Streaming": "ESTERNO. Percentili nella sezione, winsorizzati 5-95: 35% volume visite Wikipedia "
                                "(it, poi en), 35% momentum Wikipedia, 30% popolarita' TMDB (se c'e' la chiave). "
                                "Componente mancante = 0.5 (neutra). Solo opere dell'anno scorso o piu' recenti. "
                                "Senza fonte esterna: in coda per score editoriale",
        "Momentum": "log2((visite/gg ultimi R + k) / (visite/gg R precedenti + k)), k = mediana visite/gg della sezione",
        "Score Festival": "EDITORIALE (article_scoring.py), articolo migliore del gruppo; utenti attivi giornalieri "
                          "sommati nella finestra (approssimazione) e percentili su tutto il sito",
        "Fase": f"Novita' = prima pubblicazione negli ultimi R giorni; In crescita/In calo = |momentum| >= {MOMENTUM_BAND}",
        "Esclusioni": "Articoli 'streaming gratis' e '5 attrici ... pornostar' (scelta editoriale)",
    }
    if not args.no_external and not args.no_save_db:
        from data_access.db import get_connection

        long_df = signal_sources.to_long(articles, clusters, start, end, dt.date.today())
        with get_connection() as conn:
            n = signal_sources.save_long(conn, long_df)
        print(f"fact_article_signal: {n} righe scritte ({signal_sources.METHOD_VERSION}).")
    path = args.output or ROOT / "output" / f"best_of_trend_{start:%Y%m%d}_{end:%Y%m%d}.xlsx"
    write_excel(clusters, articles, daily_all, path, meta, args.min_views)

    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 48)
    print("\n=== Copertura dei segnali esterni (titoli = gruppi di articoli sulla stessa opera) ===")
    print(coverage_table(clusters, args.min_views).drop(columns=["Articoli con almeno una fonte"]).to_string(index=False))

    show = ["titolo", "trend_score", "fonte_score", "fase", "wiki_views", "tmdb_pop", "momentum", "editorial_score", "views"]
    for section in SECTION_PRIORITY:
        g = clusters[(clusters["section"] == section) & clusters["in_classifica"]]
        print(f"\n=== {section} ({len(g)} contenuti in classifica) ===")
        print(g.head(args.top)[show].round(2).to_string(index=False) if not g.empty else "(nessuno)")
    print(f"\nFile: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
