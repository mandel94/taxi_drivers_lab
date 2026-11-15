"""
signal_sources.py

Altre fonti di popolarita' ESTERNE al nostro pubblico, oltre a Wikipedia e TMDB
(che stanno in external_trend.py). Ogni fonte e' indipendente: restituisce, per un
titolo, un dizionario di colonne (None se non trova niente) e non si combina con le altre.

  imdb    numero di voti IMDb (dataset ufficiale title.ratings.tsv.gz, ~9 MB, uso non
          commerciale). L'abbinamento passa da TMDB (external_ids -> id IMDb): serve la chiave TMDB.
  gt      Google Trends Italia, accesso NON ufficiale (pytrends): interesse di ricerca del
          titolo rapportato a un termine ancora (cosi' i titoli sono confrontabili tra loro).
          Fragile: Google limita le richieste; se risponde 429 la fonte si ferma per quella esecuzione.
  yt      YouTube Data API: visualizzazioni del trailer. Chiave gratuita YOUTUBE_API_KEY.
          La ricerca costa 100 unita' di quota su 10.000 al giorno: tetto MAX_YT_SEARCHES a esecuzione.
  trakt   Trakt: spettatori, visioni, liste, commenti. Chiave gratuita TRAKT_CLIENT_ID.
  rt      Rotten Tomatoes: Tomatometer, pubblico, numero di recensioni (lettura della pagina
          pubblica del titolo: e' una valutazione, non una popolarita'; fragile se il sito cambia).

Una fonte senza chiave o senza libreria viene saltata con un avviso. Le risposte si salvano in
output/cache/<fonte>.json (le ricerche non si ripetono); i valori che cambiano nel tempo
(voti, visualizzazioni, spettatori) si salvano anche in output/cache/snapshots.csv, per
calcolare la variazione nelle esecuzioni successive.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import re
import shutil
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

import external_trend as ex

CACHE_DIR = ex.CACHE_PATH.parent
SNAPSHOTS = CACHE_DIR / "snapshots.csv"
IMDB_RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
IMDB_RATINGS_PATH = CACHE_DIR / "imdb_title_ratings.tsv.gz"
GT_ANCHOR = "trailer"  # termine ancora: media dell'interesse molto piu' stabile di un titolo
MAX_YT_SEARCHES = 90
UA = ex.USER_AGENT


@dataclass
class Ctx:
    start: dt.date
    end: dt.date
    r: int
    min_year: int
    today: dt.date
    tmdb_key: str | None = None
    tmdb_items: dict = field(default_factory=dict)  # cluster_id -> item TMDB (id, media_type, ...)
    counters: dict = field(default_factory=dict)


# (colonna, intestazione Excel, testo?, popolarita'?)  popolarita' = ottiene uno score 0-100 per sezione
COLUMNS = [
    ("imdb_id", "ID IMDb", True, False), ("imdb_votes", "IMDb voti", False, True),
    ("imdb_votes_prev", "IMDb voti R gg fa", False, False), ("imdb_rating", "IMDb voto medio", False, False),
    ("gt_ratio", "Google Trends (rapporto con ancora)", False, True),
    ("gt_recent", "Google Trends ultimi R gg", False, False), ("gt_prior", "Google Trends R gg precedenti", False, False),
    ("gt_momentum", "Google Trends momentum (log2)", False, True),
    ("yt_video", "Video YouTube", True, False), ("yt_views", "YouTube views trailer", False, True),
    ("yt_views_prev", "YouTube views R gg fa", False, False), ("yt_published", "YouTube data trailer", True, False),
    ("trakt_title", "Voce Trakt", True, False), ("trakt_watchers", "Trakt spettatori", False, True),
    ("trakt_plays", "Trakt visioni", False, False), ("trakt_lists", "Trakt liste", False, False),
    ("trakt_comments", "Trakt commenti", False, False),
    ("rt_url", "Pagina Rotten Tomatoes", True, False), ("rt_critics", "RT Tomatometer (%)", False, False),
    ("rt_audience", "RT pubblico (%)", False, False), ("rt_reviews", "RT n. recensioni", False, False),
]
SOURCE_COLUMNS = {
    "imdb": ["imdb_id", "imdb_votes", "imdb_votes_prev", "imdb_rating"],
    "gt": ["gt_ratio", "gt_recent", "gt_prior", "gt_momentum"],
    "yt": ["yt_video", "yt_views", "yt_views_prev", "yt_published"],
    "trakt": ["trakt_title", "trakt_watchers", "trakt_plays", "trakt_lists", "trakt_comments"],
    "rt": ["rt_url", "rt_critics", "rt_audience", "rt_reviews"],
}
# colonna "chiave": se e' valorizzata la fonte ha trovato il titolo
PRESENCE = {"imdb": "imdb_votes", "gt": "gt_ratio", "yt": "yt_views", "trakt": "trakt_watchers", "rt": "rt_critics"}
# fonti pesanti (una richiesta per titolo, lente o a quota): solo titoli in classifica
HEAVY = {"gt", "yt", "rt"}


# ------------------------------------------------------------------ cache e rete


class _Json:
    def __init__(self, name: str):
        self.path = CACHE_DIR / f"{name}.json"
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")


def _http(url: str, headers: dict | None = None, pause: float = 0.2, as_json: bool = True):
    time.sleep(pause)
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", "replace")
    except Exception:
        return None
    if not as_json:
        return body
    try:
        return json.loads(body)
    except ValueError:
        return None


def _env(name: str) -> str | None:
    ex.tmdb_key()  # carica il .env
    return (os.getenv(name) or "").strip() or None


def _snapshot(source: str, key: str, value: float, today: dt.date) -> None:
    new = pd.DataFrame([{"date": today.isoformat(), "source": source, "key": key, "value": value}])
    if SNAPSHOTS.exists():
        new = pd.concat([pd.read_csv(SNAPSHOTS, dtype={"key": str}), new])
    SNAPSHOTS.parent.mkdir(parents=True, exist_ok=True)
    new.drop_duplicates(["date", "source", "key"], keep="last").to_csv(SNAPSHOTS, index=False)


def _previous(source: str, key: str, today: dt.date, min_days: int) -> float | None:
    if not SNAPSHOTS.exists():
        return None
    h = pd.read_csv(SNAPSHOTS, dtype={"key": str})
    h = h[(h["source"] == source) & (h["key"] == key) & (h["date"] <= (today - dt.timedelta(days=min_days)).isoformat())]
    return float(h.sort_values("date").iloc[-1]["value"]) if not h.empty else None


# ------------------------------------------------------------------------ IMDb


class Imdb:
    name = "imdb"

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.cache = _Json("imdb")
        self.ratings: pd.DataFrame | None = None
        self.ok = bool(ctx.tmdb_key)
        if not self.ok:
            print("IMDb: serve TMDB_API_KEY (l'abbinamento passa da TMDB), salto.")

    def _load_ratings(self) -> pd.DataFrame:
        if self.ratings is None:
            fresh = IMDB_RATINGS_PATH.exists() and time.time() - IMDB_RATINGS_PATH.stat().st_mtime < 86400
            if not fresh:
                print("IMDb: scarico title.ratings.tsv.gz (~9 MB)...", flush=True)
                IMDB_RATINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
                tmp = IMDB_RATINGS_PATH.with_suffix(".tmp")
                req = urllib.request.Request(IMDB_RATINGS_URL, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as fh:
                    shutil.copyfileobj(resp, fh)
                tmp.replace(IMDB_RATINGS_PATH)
            with gzip.open(IMDB_RATINGS_PATH, "rt", encoding="utf-8") as fh:
                self.ratings = pd.read_csv(fh, sep="\t", index_col="tconst")
        return self.ratings

    def _imdb_id(self, item: dict) -> str | None:
        key = f"ext|{item['media_type']}|{item['id']}"
        if key not in self.cache.data:
            res = ex._tmdb_get(f"/{item['media_type']}/{item['id']}/external_ids", {}, self.ctx.tmdb_key)
            if res is None:
                return None  # errore di rete: non lo memorizzo
            self.cache.data[key] = res.get("imdb_id") or None
        return self.cache.data[key]

    def lookup(self, cid: str, label: str) -> dict | None:
        item = self.ctx.tmdb_items.get(cid)
        if not self.ok or not item:
            return None
        tconst = self._imdb_id(item)
        if not tconst:
            return None
        ratings = self._load_ratings()
        if tconst not in ratings.index:
            return None
        row = ratings.loc[tconst]
        votes = float(row["numVotes"])
        _snapshot("imdb", tconst, votes, self.ctx.today)
        return {"imdb_id": tconst, "imdb_votes": votes, "imdb_rating": float(row["averageRating"]),
                "imdb_votes_prev": _previous("imdb", tconst, self.ctx.today, self.ctx.r)}

    def close(self) -> None:
        self.cache.save()


# ---------------------------------------------------------------- Google Trends


class GoogleTrends:
    name = "gt"

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.cache = _Json("google_trends")
        self.blocked = False
        try:
            from pytrends.request import TrendReq

            self.client = TrendReq(hl="it-IT", tz=-60, timeout=(10, 30))
            self.ok = True
        except Exception:
            print("Google Trends: pytrends non installato (pip install pytrends), salto.")
            self.ok = False

    def lookup(self, cid: str, label: str) -> dict | None:
        if not self.ok or self.blocked:
            return None
        c = self.ctx
        key = f"{c.start}|{c.end}|{c.r}|{ex._norm(label)}"
        if key in self.cache.data:
            return self.cache.data[key]
        timeframe = f"{c.start:%Y-%m-%d} {c.end:%Y-%m-%d}"
        for attempt in range(3):
            try:
                time.sleep(2.5)
                self.client.build_payload([GT_ANCHOR, label], timeframe=timeframe, geo="IT")
                df = self.client.interest_over_time()
                break
            except Exception as exc:  # 429 e simili: pausa, poi si rinuncia per questa esecuzione
                wait = 45 * (attempt + 1)
                print(f"  Google Trends: {type(exc).__name__}, attendo {wait}s", flush=True)
                time.sleep(wait)
        else:
            self.blocked = True
            print("  Google Trends: troppe risposte negative, la fonte si ferma per questa esecuzione.")
            return None
        if df is None or df.empty or label not in df or float(df[GT_ANCHOR].mean()) == 0:
            res = None
        else:
            anchor = float(df[GT_ANCHOR].mean())
            title = df[label].astype(float)
            ratio = float(title.mean()) / anchor
            recent, prior = float(title.iloc[-c.r:].mean()) / anchor, float(title.iloc[-2 * c.r:-c.r].mean()) / anchor
            k = 0.02  # evita variazioni enormi quando il titolo e' quasi a zero
            res = {"gt_ratio": ratio, "gt_recent": recent, "gt_prior": prior,
                   "gt_momentum": float(np.log2((recent + k) / (prior + k)))} if ratio > 0 else None
        self.cache.data[key] = res
        return res

    def close(self) -> None:
        self.cache.save()


# ---------------------------------------------------------------------- YouTube


class YouTube:
    name = "yt"
    BASE = "https://www.googleapis.com/youtube/v3"

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.key = _env("YOUTUBE_API_KEY")
        self.cache = _Json("youtube")
        self.searches = 0
        self.exhausted = False
        self.ok = bool(self.key)
        if not self.ok:
            print("YouTube: YOUTUBE_API_KEY non impostata, salto.")

    def _api(self, path: str, params: dict) -> dict | None:
        url = f"{self.BASE}/{path}?{urllib.parse.urlencode({**params, 'key': self.key})}"
        time.sleep(0.1)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code == 403:  # quota finita
                self.exhausted = True
                print("  YouTube: quota esaurita, la fonte si ferma per questa esecuzione.")
            return None
        except Exception:
            return None

    def _find_video(self, label: str) -> dict | None:
        key = f"search|{self.ctx.min_year}|{ex._norm(label)}"
        if key in self.cache.data:
            return self.cache.data[key]
        if self.exhausted or self.searches >= MAX_YT_SEARCHES:
            return None
        self.searches += 1
        after = dt.datetime(self.ctx.min_year, 1, 1).strftime("%Y-%m-%dT00:00:00Z")
        res = self._api("search", {"part": "snippet", "q": f"{label} trailer ufficiale", "type": "video",
                                   "regionCode": "IT", "relevanceLanguage": "it", "maxResults": 8,
                                   "publishedAfter": after})
        if res is None:
            return None
        want, found = ex._norm(label), None
        for it in res.get("items", []):
            title = ex._norm(it["snippet"]["title"])
            if want in title and "trailer" in title:
                found = {"id": it["id"]["videoId"], "title": it["snippet"]["title"],
                         "published": it["snippet"]["publishedAt"][:10]}
                break
        self.cache.data[key] = found
        return found

    def lookup(self, cid: str, label: str) -> dict | None:
        if not self.ok:
            return None
        video = self._find_video(label)
        if not video:
            return None
        res = self._api("videos", {"part": "statistics", "id": video["id"]})
        items = (res or {}).get("items", [])
        if not items or "viewCount" not in items[0].get("statistics", {}):
            return None
        views = float(items[0]["statistics"]["viewCount"])
        _snapshot("yt", video["id"], views, self.ctx.today)
        return {"yt_video": f"{video['title']} ({video['id']})", "yt_views": views,
                "yt_published": video["published"],
                "yt_views_prev": _previous("yt", video["id"], self.ctx.today, self.ctx.r)}

    def close(self) -> None:
        self.cache.save()


# ------------------------------------------------------------------------ Trakt


class Trakt:
    name = "trakt"
    BASE = "https://api.trakt.tv"

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.cid = _env("TRAKT_CLIENT_ID")
        self.cache = _Json("trakt")
        self.ok = bool(self.cid)
        if not self.ok:
            print("Trakt: TRAKT_CLIENT_ID non impostata, salto.")

    def _api(self, path: str, params: dict | None = None):
        url = f"{self.BASE}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
        return _http(url, {"trakt-api-version": "2", "trakt-api-key": self.cid, "Content-Type": "application/json"},
                     pause=0.3)

    def lookup(self, cid: str, label: str) -> dict | None:
        if not self.ok:
            return None
        key = f"search|{self.ctx.min_year}|{ex._norm(label)}"
        if key not in self.cache.data:
            res = self._api("/search/movie,show", {"query": label, "limit": 10})
            if res is None:
                return None
            found, want = None, ex._norm(label)
            for r in res:
                kind = r.get("type")
                obj = r.get(kind) or {}
                if kind not in ("movie", "show") or ex._norm(obj.get("title", "")) != want:
                    continue
                if (obj.get("year") or 0) < self.ctx.min_year:
                    continue
                found = {"kind": kind, "id": obj["ids"]["trakt"], "title": obj["title"], "year": obj["year"]}
                break
            self.cache.data[key] = found
        hit = self.cache.data[key]
        if not hit:
            return None
        st = self._api(f"/{hit['kind']}s/{hit['id']}/stats")
        if not st:
            return None
        return {"trakt_title": f"{hit['kind']}: {hit['title']} ({hit['year']})",
                "trakt_watchers": float(st.get("watchers", 0)), "trakt_plays": float(st.get("plays", 0)),
                "trakt_lists": float(st.get("lists", 0)), "trakt_comments": float(st.get("comments", 0))}

    def close(self) -> None:
        self.cache.save()


# ------------------------------------------------------------- Rotten Tomatoes


class RottenTomatoes:
    name = "rt"
    BASE = "https://www.rottentomatoes.com"

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.cache = _Json("rotten_tomatoes")
        self.ok = True

    @staticmethod
    def _slug(label: str) -> str:
        return ex._norm(label).replace(" ", "_")

    def _parse(self, html: str) -> dict | None:
        # l'anno della pagina deve essere recente (stessa regola di Wikipedia e TMDB)
        years = [int(y) for y in re.findall(r'"(?:dateCreated|datePublished)":"(\d{4})', html)]
        if not years or max(years) < self.ctx.min_year:
            return None
        crit = re.search(r'"criticsScore":\{[^}]*?"reviewCount":(\d+)[^}]*?"scorePercent":"(\d+)%"', html)
        aud = re.search(r'"audienceScore":\{[^}]*?"scorePercent":"(\d+)%"', html)
        if not crit and not aud:
            return None
        return {"rt_critics": float(crit.group(2)) if crit else None,
                "rt_reviews": float(crit.group(1)) if crit else None,
                "rt_audience": float(aud.group(1)) if aud else None}

    def lookup(self, cid: str, label: str) -> dict | None:
        slug = self._slug(label)
        if not slug:
            return None
        key = f"rt|{self.ctx.min_year}|{slug}"
        stored = self.cache.data.get(key)
        fresh = dt.date.fromisoformat(stored["on"]) >= self.ctx.today - dt.timedelta(days=3) if stored else False
        if stored and (fresh or stored["data"] is None):  # un "non trovato" non si riprova
            return stored["data"]
        data = None
        for path in (f"/m/{slug}", f"/m/{slug}_{self.ctx.end.year}", f"/tv/{slug}/s01", f"/tv/{slug}"):
            html = _http(self.BASE + path, {"Accept-Language": "en"}, pause=1.0, as_json=False)
            if html:
                data = self._parse(html)
                if data:
                    data["rt_url"] = self.BASE + path
                    break
        self.cache.data[key] = {"on": self.ctx.today.isoformat(), "data": data}
        return data

    def close(self) -> None:
        self.cache.save()


SOURCES = {"imdb": Imdb, "gt": GoogleTrends, "yt": YouTube, "trakt": Trakt, "rt": RottenTomatoes}


# ------------------------------------------------------------------ esecuzione


def ensure_columns(c: pd.DataFrame) -> None:
    for col, _, is_text, _ in COLUMNS:
        if col not in c:
            c[col] = None if is_text else np.nan
            if is_text:
                c[col] = c[col].astype(object)


def run(c: pd.DataFrame, ctx: Ctx, enabled: list[str]) -> None:
    """Riempie in `c` le colonne delle fonti abilitate. Le fonti pesanti vedono solo i titoli in classifica."""
    ensure_columns(c)
    for name in enabled:
        src = SOURCES[name](ctx)
        if not src.ok:
            continue
        mask = c["cercato"].copy()
        if name in HEAVY:
            mask &= c["in_classifica"]
        todo = c[mask]
        print(f"{name}: cerco {len(todo)} titoli...", flush=True)
        n = 0
        for i, (cid, row) in enumerate(todo.iterrows(), start=1):
            if i % 25 == 0:
                print(f"  {name} {i}/{len(todo)}", flush=True)
                src.close()
            res = src.lookup(cid, row["titolo"])
            if res:
                n += 1
                for col, val in res.items():
                    c.loc[cid, col] = val if val is not None else (None if col in _TEXT else np.nan)
        src.close()
        print(f"  {name}: trovati {n} su {len(todo)}", flush=True)


_TEXT = {col for col, _, is_text, _ in COLUMNS if is_text}


METHOD_VERSION = "signals-v1"
# (fonte, metrica, colonna in `clusters`, colonna con la voce abbinata, a finestra?)
LONG_MAP = [
    ("wikipedia", "views", "wiki_views", "wiki_pagina", True),
    ("wikipedia", "views_recent", "wiki_recent", "wiki_pagina", True),
    ("wikipedia", "views_prior", "wiki_prior", "wiki_pagina", True),
    ("wikipedia", "momentum_log2", "momentum", "wiki_pagina", True),
    ("tmdb", "popularity", "tmdb_pop", "tmdb_titolo", False),
    ("imdb", "votes", "imdb_votes", "imdb_id", False),
    ("imdb", "rating", "imdb_rating", "imdb_id", False),
    ("google_trends", "interest_ratio", "gt_ratio", None, True),
    ("google_trends", "interest_recent", "gt_recent", None, True),
    ("google_trends", "interest_prior", "gt_prior", None, True),
    ("google_trends", "momentum_log2", "gt_momentum", None, True),
    ("youtube", "trailer_views", "yt_views", "yt_video", False),
    ("trakt", "watchers", "trakt_watchers", "trakt_title", False),
    ("trakt", "plays", "trakt_plays", "trakt_title", False),
    ("trakt", "lists", "trakt_lists", "trakt_title", False),
    ("trakt", "comments", "trakt_comments", "trakt_title", False),
    ("rotten_tomatoes", "critics_pct", "rt_critics", "rt_url", False),
    ("rotten_tomatoes", "audience_pct", "rt_audience", "rt_url", False),
    ("rotten_tomatoes", "reviews", "rt_reviews", "rt_url", False),
]


def to_long(articles: pd.DataFrame, clusters: pd.DataFrame, start: dt.date, end: dt.date,
            as_of: dt.date) -> pd.DataFrame:
    """Segnali in formato lungo, una riga per (articolo, fonte, metrica) con valore presente.

    `articles` ha article_id e cluster_id; `clusters` e' indicizzato per cluster_id e ha
    le colonne di LONG_MAP. I valori sono dell'opera: si ripetono per ogni suo articolo.
    """
    frames = []
    link = articles[["article_id", "cluster_id"]].drop_duplicates()
    for source, metric, col, entry_col, windowed in LONG_MAP:
        if col not in clusters:
            continue
        sub = clusters.loc[clusters[col].notna(), [col, "titolo"] + ([entry_col] if entry_col else [])]
        if sub.empty:
            continue
        if "cluster_id" in clusters:  # dopo build_clusters l'id e' una colonna
            sub = sub.assign(_cid=clusters.loc[sub.index, "cluster_id"].to_numpy())
        else:
            sub = sub.rename_axis("_cid").reset_index()
        df = link.merge(sub, left_on="cluster_id", right_on="_cid", how="inner")
        frames.append(pd.DataFrame({
            "article_id": df["article_id"].astype(int), "source": source, "metric": metric,
            "as_of_date": as_of, "window_start": start if windowed else as_of,
            "window_end": end if windowed else as_of, "method_version": METHOD_VERSION,
            "value": df[col].astype(float),
            "source_entry": df[entry_col] if entry_col else None, "work_label": df["titolo"],
        }))
    if not frames:
        return pd.DataFrame(columns=["article_id", "source", "metric", "as_of_date", "window_start",
                                     "window_end", "method_version", "value", "source_entry", "work_label"])
    out = pd.concat(frames, ignore_index=True)
    return out[np.isfinite(out["value"])].reset_index(drop=True)


def save_long(conn, long_df: pd.DataFrame) -> int:
    """Upsert idempotente in fact_article_signal; restituisce le righe scritte."""
    from psycopg2.extras import execute_values

    if long_df.empty:
        return 0
    cols = ["article_id", "source", "metric", "as_of_date", "window_start", "window_end",
            "method_version", "value", "source_entry", "work_label"]
    rows = [tuple(None if (isinstance(v, float) and np.isnan(v)) or v is pd.NA or v is None else
                  (v.item() if hasattr(v, "item") else v) for v in rec)
            for rec in long_df[cols].itertuples(index=False, name=None)]
    sql = (f"INSERT INTO fact_article_signal ({', '.join(cols)}) VALUES %s "
           "ON CONFLICT (article_id, source, metric, as_of_date, window_start, window_end, method_version) "
           "DO UPDATE SET value = EXCLUDED.value, source_entry = EXCLUDED.source_entry, "
           "work_label = EXCLUDED.work_label, computed_at = now()")
    with conn.cursor() as cur:
        execute_values(cur, sql, rows, page_size=2000)
    conn.commit()
    return len(rows)


def add_ranks(c: pd.DataFrame, rank_fn) -> None:
    """Score 0-100 per sezione (percentile tra i titoli che hanno il segnale), una colonna per metrica di popolarita'."""
    for col, _, _, is_pop in COLUMNS:
        if not is_pop:
            continue
        rcol = f"r_{col}"
        c[rcol] = np.nan
        for section in c["section"].unique():
            m = c["section"].eq(section) & c[col].notna()
            if m.sum():
                vals = np.log1p(c.loc[m, col]) if col not in ("gt_momentum",) else c.loc[m, col]
                c.loc[m, rcol] = rank_fn(vals)
