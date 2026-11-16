"""
nlp/midreport_insight/observe.py

Fase 1 del modulo di insight del midreport: osservazioni (fatti con numero, campione e
confronto con lo storico, nessuna causa). Contratto: nlp/midreport_insight/README.md.
Solo pandas/numpy/stdlib, nessuna rete.

CLI:
    python -m nlp.midreport_insight.observe --week AAAA-MM-GG [--kb <cartella>] [--out <file>]
"""

import argparse
import json
import math
import os
import pathlib
import re
import sys
import unicodedata

import numpy as np
import pandas as pd

MIN_CATEGORY_ARTICLES = 5
MIN_USERS_ER = 20
MIN_EXPOSURE_DAYS = 3
MIN_GROUP_N = 5
MIN_HISTORY_WEEKS = 4

DEFAULT_KB = (r"C:\Users\manuel.deluzi\OneDrive - Havas\Projects\personali\taxi_drivers"
              r"\reports\weekly\Insight KB")
HISTORY_FILE = "articles_history.csv"

PATTERN_DIMENSIONS = ["format", "pub_weekday", "pub_hour_bucket", "age_group", "length_bucket",
                      "has_question", "starts_with_number", "has_colon", "author"]

_DIM_LABELS = {
    "format": "Formato",
    "pub_weekday": "Giorno di pubblicazione",
    "pub_hour_bucket": "Fascia oraria",
    "age_group": "Età dell'articolo",
    "length_bucket": "Lunghezza del titolo",
    "has_question": "Titolo con punto interrogativo",
    "starts_with_number": "Titolo che inizia con un numero",
    "has_colon": "Titolo con due punti",
    "author": "Autore",
}

TABLE_COLUMNS = [
    "article_id", "title", "author", "category", "format", "pub_date", "pub_weekday",
    "pub_hour_bucket", "age_days", "age_group", "exposure_days", "users", "er", "dur",
    "has_question", "starts_with_number", "has_colon", "n_chars", "length_bucket", "topic",
    "baseline_users", "ratio_vs_baseline", "prev_week_id", "prev_users",
]

_WEEKDAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
_MONTHS = ("gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|"
           "novembre|dicembre")

_RE_LIST_START = re.compile(r"^\s*(?:(?:i|le|gli|top|ecco)\s+)?\d{1,2}(?!\d)\s+\w")
_RE_LIST_MONTH = re.compile(r"(?:%s)\s+\d{4}(?!\d)" % _MONTHS)
_RE_NUM_START = re.compile(r"^\s*(?:(?:i|le|gli|top|ecco)\s+)?\d")

# apertura -> caratteri di chiusura ammessi
_QUOTE_PAIRS = {
    "\u2018": ("\u2019", "'"),
    "'": ("'", "\u2019"),
    "\u201c": ("\u201d",),
    "\u00ab": ("\u00bb",),
}


# ---------------------------------------------------------------- formattazione

def _d(x, dec=1):
    return f"{x:.{dec}f}".replace(".", ",")


def _sd(x, dec=1):
    return f"{x:+.{dec}f}".replace(".", ",")


def _n(x):
    return f"{int(round(x)):,}".replace(",", ".")


def _jsonable(o):
    if o is pd.NaT or o is None:
        return None
    if isinstance(o, dict):
        return {(k if isinstance(k, str) else str(k)): _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%d")
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, str):
        return o
    try:
        if pd.isna(o):
            return None
    except (TypeError, ValueError):
        pass
    return str(o)


# ---------------------------------------------------------------- titoli

def _norm(s):
    return unicodedata.normalize("NFC", s if isinstance(s, str) else "").lower()


def classify_format(title, category):
    t = _norm(title)
    c = _norm(category).strip()
    if c == "interviste" or "intervista" in t:
        return "intervista"
    if c == "trailers" or "trailer" in t:
        return "trailer"
    if (_RE_LIST_START.match(t) or any(k in t for k in ("migliori", "guida", "classifica",
                                                        "dove vedere"))
            or _RE_LIST_MONTH.search(t)):
        return "guida_lista"
    if c == "recensioni" or t.lstrip().startswith("recensione"):
        return "recensione"
    if c == "si farà" or "si farà" in t:
        return "si_fara"
    if c == "anticipazioni":
        return "anticipazione"
    if c == "festival di cinema":
        return "festival"
    if c == "news":
        return "news"
    return "altro"


def extract_topic(title):
    if not isinstance(title, str):
        return None
    n = len(title)
    for i, ch in enumerate(title):
        if ch not in _QUOTE_PAIRS:
            continue
        if ch == "'" and i > 0 and title[i - 1].isalnum():
            continue
        closers = _QUOTE_PAIRS[ch]
        for j in range(i + 1, n):
            if title[j] in closers and (j + 1 == n or not title[j + 1].isalnum()):
                seg = title[i + 1:j].strip()
                if seg:
                    return seg
                break
    return None


def title_features(title):
    t = title if isinstance(title, str) else ""
    n = len(t)
    return {
        "has_question": "?" in t,
        "starts_with_number": bool(_RE_NUM_START.match(t.lower())),
        "has_colon": ":" in t,
        "n_chars": n,
        "length_bucket": "corto" if n < 50 else ("medio" if n <= 80 else "lungo"),
        "topic": extract_topic(t),
    }


# ---------------------------------------------------------------- preparazione

def _to_bool(s):
    if s.dtype == bool:
        return s
    m = {"true": True, "1": True, "1.0": True, "yes": True, "si": True,
         "false": False, "0": False, "0.0": False, "no": False}
    return s.astype(str).str.strip().str.lower().map(m).fillna(False).astype(bool)


def _prep(history):
    """Copia normalizzata: tipi coerenti, righe `excluded` rimosse."""
    h = history.copy()
    h["week_id"] = h["week_id"].astype(str).str[:10]
    for c in ("period_start", "period_end", "pub_date"):
        h[c] = pd.to_datetime(h[c], errors="coerce").dt.normalize()
    h["comparable"] = _to_bool(h["comparable"])
    h["excluded"] = _to_bool(h["excluded"])
    for c in ("users", "er", "dur"):
        h[c] = pd.to_numeric(h[c], errors="coerce")
    h = h[~h["excluded"]]
    # traffico sospetto: stessa regola della KB (engagement < 5%, durata < 3 s, almeno 20 utenti).
    # La KB lo toglie nel pack, ma resta in articles_history.csv.
    bot = (h["er"] < 0.05) & (h["dur"] < 3) & (h["users"] >= MIN_USERS_ER)
    return h[~bot].reset_index(drop=True)


def _weeks(h):
    return h.groupby("week_id").agg(period_start=("period_start", "min"),
                                    period_end=("period_end", "max"),
                                    comparable=("comparable", "all"))


def _prev_week(weeks, week_id):
    c = weeks[weeks["comparable"].to_numpy() & (weeks.index < week_id)]
    return c.index.max() if len(c) else None


def _age_group(ps, pub):
    days = (ps - pub).dt.days
    g = pd.Series(np.where(pub >= ps, "in_settimana",
                           np.where(days <= 7, "1-7gg",
                                    np.where(days <= 30, "8-30gg", "oltre_30gg"))),
                  index=ps.index, dtype=object)
    g[pub.isna()] = None
    return g


def _hour_bucket(x):
    if pd.isna(x):
        return None
    if x < 6:
        return "notte"
    if x < 12:
        return "mattina"
    if x < 18:
        return "pomeriggio"
    return "sera"


# ---------------------------------------------------------------- build_table

def _build(h, week_id):
    cur = h[h["week_id"] == week_id].copy()
    if cur.empty:
        return pd.DataFrame(columns=TABLE_COLUMNS)
    ps, pe, pub = cur["period_start"], cur["period_end"], cur["pub_date"]

    out = pd.DataFrame(index=cur.index)
    for c in ("article_id", "title", "author", "category", "pub_date", "users", "er", "dur"):
        out[c] = cur[c]
    out["format"] = [classify_format(t, c) for t, c in zip(cur["title"], cur["category"])]
    out["pub_weekday"] = [None if pd.isna(p) else _WEEKDAYS[p.dayofweek] for p in pub]
    if "pub_hour" in cur.columns:
        hours = pd.to_numeric(cur["pub_hour"], errors="coerce")
        out["pub_hour_bucket"] = pd.Series([_hour_bucket(x) for x in hours],
                                           index=cur.index, dtype=object)
    else:
        out["pub_hour_bucket"] = pd.Series([None] * len(cur), index=cur.index, dtype=object)
    out["age_days"] = (ps - pub).dt.days.clip(lower=0)
    out["age_group"] = _age_group(ps, pub)
    start = pub.where(pub >= ps, ps)
    out["exposure_days"] = (pe - start).dt.days + 1

    feats = pd.DataFrame([title_features(t) for t in cur["title"]], index=cur.index)
    for c in ("has_question", "starts_with_number", "has_colon", "n_chars", "length_bucket",
              "topic"):
        out[c] = feats[c]

    # baseline: settimane comparabili diverse da week_id, age_group sul proprio period_start
    hist = h[h["comparable"] & (h["week_id"] != week_id)].copy()
    hist["age_group"] = _age_group(hist["period_start"], hist["pub_date"])
    hist = hist.dropna(subset=["users", "age_group", "category"])
    base = {}
    if not hist.empty:
        g = hist.groupby(["category", "age_group"])["users"].agg(["median", "count"])
        for key, row in g.iterrows():
            if row["count"] >= MIN_GROUP_N:
                base[key] = float(row["median"])
    out["baseline_users"] = [base.get((c, a), np.nan)
                             for c, a in zip(out["category"], out["age_group"])]
    b = out["baseline_users"]
    out["ratio_vs_baseline"] = (out["users"] / b).where(b > 0)

    weeks = _weeks(h)
    prev = _prev_week(weeks, week_id)
    out["prev_week_id"] = pd.Series([prev] * len(cur), index=cur.index, dtype=object)
    if prev is not None:
        pu = h[h["week_id"] == prev].drop_duplicates("article_id").set_index("article_id")["users"]
        out["prev_users"] = cur["article_id"].map(pu).astype(float)
    else:
        out["prev_users"] = np.nan

    return out[TABLE_COLUMNS].reset_index(drop=True)


def build_table(history, week_id):
    return _build(_prep(history), str(week_id))


# ---------------------------------------------------------------- categorie

def _cat_fact(o):
    parts = [f"{o['category']}: {_n(o['n_articles'])} articoli, {_n(o['users'])} utenti, "
             f"quota {_d(o['share_pct'])}% degli utenti della settimana, "
             f"{_d(o['users_per_article'])} utenti per articolo"]
    if o["normal_share_pct"] is not None:
        parts.append(f"mediana delle {o['n_history_weeks']} settimane comparabili di storico: "
                     f"quota {_d(o['normal_share_pct'])}% ({_sd(o['share_delta_pp'])} punti "
                     f"percentuali), {_d(o['normal_users_per_article'])} utenti per articolo")
    else:
        parts.append(f"storico insufficiente ({o['n_history_weeks']} settimane con la "
                     f"categoria, minimo {MIN_HISTORY_WEEKS})")
    if not o["sample_ok"]:
        parts.append(f"campione piccolo (minimo {MIN_CATEGORY_ARTICLES} articoli)")
    if o["prev_share_pct"] is not None:
        parts.append(f"settimana comparabile precedente: quota {_d(o['prev_share_pct'])}%")
    return "; ".join(parts) + "."


def _category_observations(table, h, week_id):
    if table.empty:
        return []
    total = float(table["users"].fillna(0).sum())
    hist = h[h["comparable"] & (h["week_id"] != week_id)]
    if hist.empty:
        weekly = pd.DataFrame(columns=["week_id", "category", "users", "n", "share"])
    else:
        wk_tot = hist.groupby("week_id")["users"].sum()
        weekly = (hist.groupby(["week_id", "category"])
                  .agg(users=("users", "sum"), n=("article_id", "size")).reset_index())
        weekly["total"] = weekly["week_id"].map(wk_tot)
        weekly = weekly[weekly["total"] > 0].copy()
        weekly["share"] = weekly["users"] / weekly["total"] * 100
    prev = _prev_week(_weeks(h), week_id)

    obs = []
    for cat, grp in table.groupby("category", sort=False):
        users = float(grp["users"].fillna(0).sum())
        n_art = int(len(grp))
        share = users / total * 100 if total > 0 else 0.0
        erg = grp[grp["er"].notna() & (grp["users"] > 0)]
        er_w = (float(np.average(erg["er"], weights=erg["users"]))
                if not erg.empty else None)
        ch = weekly[weekly["category"] == cat]
        n_hist = int(len(ch))
        ok_hist = n_hist >= MIN_HISTORY_WEEKS
        sample_ok = n_art >= MIN_CATEGORY_ARTICLES

        o = {"category": cat, "n_articles": n_art, "users": users, "share_pct": share,
             "users_per_article": users / n_art, "er_weighted": er_w}
        normal_share = None
        if ok_hist:
            normal_share = float(ch["share"].median())
            o["normal_share_pct"] = normal_share
            o["normal_users"] = float(ch["users"].median())
            o["normal_users_per_article"] = float((ch["users"] / ch["n"]).median())
            o["share_delta_pp"] = share - normal_share
            o["share_ratio"] = share / normal_share if normal_share > 0 else None
            std = float(ch["share"].std(ddof=1))
            o["z"] = (share - float(ch["share"].mean())) / std if std > 0 else None
        else:
            for k in ("normal_share_pct", "normal_users", "normal_users_per_article",
                      "share_delta_pp", "share_ratio", "z"):
                o[k] = None
        ps = None
        if prev is not None:
            pr = weekly[(weekly["week_id"] == prev) & (weekly["category"] == cat)]
            if not pr.empty:
                ps = float(pr["share"].iloc[0])
        o["prev_share_pct"] = ps

        top = grp.loc[grp["users"].fillna(-1).idxmax()]
        o["top1_title"] = top["title"]
        o["top1_share_of_category"] = (float(top["users"]) / users) if users > 0 else None
        o["n_history_weeks"] = n_hist
        o["sample_ok"] = sample_ok
        ratio = o["share_ratio"]
        if not ok_hist or not sample_ok or ratio is None:
            o["direction"] = None
        elif ratio >= 1.25:
            o["direction"] = "su"
        elif ratio <= 0.8:
            o["direction"] = "giu"
        else:
            o["direction"] = "stabile"
        o["fact"] = _cat_fact(o)
        obs.append(o)

    obs.sort(key=lambda r: r["share_pct"], reverse=True)
    return _jsonable(obs)


def category_observations(table, history, week_id):
    return _category_observations(table, _prep(history), str(week_id))


# ---------------------------------------------------------------- top / worst

def select_top_worst(table, per_cat=2):
    parts = []
    for cat, grp in table.groupby("category", sort=False):
        if len(grp) < MIN_CATEGORY_ARTICLES:
            continue
        top = grp.sort_values("users", ascending=False, kind="mergesort").head(per_cat)
        rest = grp[~grp["article_id"].isin(top["article_id"])]
        cand = rest[(rest["exposure_days"] >= MIN_EXPOSURE_DAYS)
                    & (rest["baseline_users"] >= 10)
                    & rest["ratio_vs_baseline"].notna()]
        worst = cand.sort_values("ratio_vs_baseline", ascending=True, kind="mergesort").head(per_cat)
        parts.append(top.assign(role="top"))
        parts.append(worst.assign(role="worst"))
    if not parts:
        return pd.DataFrame(columns=list(table.columns) + ["role"])
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------- pattern

def _dim_stats(tbl, min_n, full=False):
    out = {}
    t = tbl[tbl["ratio_vs_baseline"].notna()]
    if t.empty:
        return out
    for dim in PATTERN_DIMENSIONS:
        if dim not in t.columns:
            continue
        sub = t.dropna(subset=[dim])
        for val, grp in sub.groupby(dim):
            if len(grp) < min_n:
                continue
            if isinstance(val, (bool, np.bool_)):
                val = bool(val)
            rec = {"n": int(len(grp)), "median_ratio": float(grp["ratio_vs_baseline"].median())}
            if full:
                rec["median_users"] = float(grp["users"].median())
                er = grp.loc[grp["users"] >= MIN_USERS_ER, "er"].dropna()
                rec["median_er"] = float(er.median()) if len(er) else None
            out[(dim, val)] = rec
    return out


def _side(x):
    return (x > 1) - (x < 1)


def _pattern_fact(p):
    val = p["value"]
    if isinstance(val, bool):
        val = "sì" if val else "no"
    s = (f"{_DIM_LABELS[p['dimension']]} = {val}: {p['n']} articoli, rapporto mediano con la "
         f"baseline {_d(p['median_ratio'], 2)}")
    extra = []
    if p["median_users"] is not None:
        extra.append(f"mediana utenti {_n(p['median_users'])}")
    if p["median_er"] is not None:
        extra.append(f"ER mediano {_d(p['median_er'] * 100)}%")
    if extra:
        s += " (" + ", ".join(extra) + ")"
    s += (f"; stesso lato rispetto a 1 in {p['weeks_same_direction']} settimane su "
          f"{p['weeks_with_data']} con dati")
    return s + "."


def _pattern_observations(table, h, week_id, min_n):
    if table.empty:
        return []
    weeks = _weeks(h)
    past = list(weeks.index[weeks["comparable"].to_numpy() & (weeks.index < week_id)])
    past_stats = [_dim_stats(_build(h, w), min_n) for w in past]
    cur_comparable = bool(weeks.loc[week_id, "comparable"]) if week_id in weeks.index else False
    cur_stats = _dim_stats(table, min_n, full=True)

    obs = []
    for (dim, val), rec in cur_stats.items():
        mr = rec["median_ratio"]
        wd = [s[(dim, val)]["median_ratio"] for s in past_stats if (dim, val) in s]
        if cur_comparable:
            wd.append(mr)
        p = {"dimension": dim, "value": val, "n": rec["n"], "median_ratio": mr,
             "median_users": rec["median_users"], "median_er": rec["median_er"],
             "notable": bool(mr >= 1.25 or mr <= 0.8),
             "weeks_with_data": len(wd),
             "weeks_same_direction": sum(1 for x in wd if _side(x) == _side(mr))}
        p["fact"] = _pattern_fact(p)
        obs.append(p)
    order = {d: i for i, d in enumerate(PATTERN_DIMENSIONS)}
    obs.sort(key=lambda p: (order[p["dimension"]], -p["n"]))
    return _jsonable(obs)


def pattern_observations(table, history, week_id, min_n=MIN_GROUP_N):
    return _pattern_observations(table, _prep(history), str(week_id), min_n)


# ---------------------------------------------------------------- settimana

def observe_week(history, week_id, per_cat=2):
    week_id = str(week_id)
    h = _prep(history)
    weeks = _weeks(h)
    table = _build(h, week_id)
    comparable = bool(weeks.loc[week_id, "comparable"]) if week_id in weeks.index else False
    n_hist = int((weeks["comparable"].to_numpy() & (weeks.index != week_id)).sum())

    flags = []
    if n_hist < MIN_HISTORY_WEEKS:
        flags.append(f"storico corto: {n_hist} settimane comparabili, minimo {MIN_HISTORY_WEEKS}")
    if week_id not in weeks.index:
        flags.append("settimana assente dalla history: nessun articolo")
    elif not comparable:
        flags.append("settimana non comparabile: confronti con lo storico da leggere con cautela")
    if "pub_hour" not in h.columns or h["pub_hour"].isna().all():
        flags.append("pub_hour assente: fascia oraria non calcolata")

    tw = select_top_worst(table, per_cat) if not table.empty else table
    return _jsonable({
        "week_id": week_id,
        "comparable": comparable,
        "n_articles": int(len(table)),
        "n_history_weeks": n_hist,
        "categories": _category_observations(table, h, week_id),
        "patterns": _pattern_observations(table, h, week_id, MIN_GROUP_N),
        "top_worst": tw.to_dict("records") if not tw.empty else [],
        "flags": flags,
    })


# ---------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="Osservazioni del midreport (fase 1)")
    ap.add_argument("--week", required=True, help="lunedi' della settimana, AAAA-MM-GG")
    ap.add_argument("--kb", default=os.environ.get("TD_INSIGHT_KB", DEFAULT_KB),
                    help="cartella della Insight KB")
    ap.add_argument("--out", default=None, help="file di output (osservazioni.json)")
    args = ap.parse_args(argv)

    csv_path = pathlib.Path(args.kb) / HISTORY_FILE
    if not csv_path.exists():
        print(f"File non trovato: {csv_path}", file=sys.stderr)
        return 1
    history = pd.read_csv(csv_path, dtype={"week_id": str, "article_id": str})
    if args.week not in set(history["week_id"].astype(str).str[:10]):
        print(f"Settimana {args.week} assente da {csv_path}", file=sys.stderr)
        return 1

    res = observe_week(history, args.week)
    if args.out:
        out = pathlib.Path(args.out)
    else:
        root = pathlib.Path(__file__).resolve().parents[2]
        out = root / "output" / "midreport_workflow" / args.week / "osservazioni.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"Scritto {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
