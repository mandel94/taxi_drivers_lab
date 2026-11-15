"""
external_trend.py

Segnali di attenzione ESTERNI al nostro pubblico, per il best of (trend_best_of.py).
Per ora una sola fonte: le visite giornaliere della voce Wikipedia dell'opera
(API pubblica Wikimedia, gratuita e senza chiave).

  1. titolo -> voce: ricerca su it.wikipedia (poi en.wikipedia) e scelta del primo
     risultato il cui titolo coincide e la cui descrizione breve dice che e' un
     film / una serie / un documentario. Niente voce = nessun segnale (None).
  2. visite giornaliere della voce (utenti reali, tutti gli accessi) nella finestra.

Le risposte si salvano in output/cache/wikipedia.json: stessa ricerca e stessi giorni
non richiamano l'API (i giorni passati non cambiano; le ultime 48 ore si riscaricano).
"""

from __future__ import annotations

import datetime as dt
import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

USER_AGENT = "taxidrivers-trend/0.1 (https://www.taxidrivers.it; manueldeluzi@gmail.com)"
CACHE_PATH = Path(__file__).resolve().parent.parent / "output" / "cache" / "wikipedia.json"
LANGS = ("it", "en")
PAUSE_S = 0.15

_WORK_DESC = re.compile(
    r"\b(film|lungometraggio|cortometraggio|documentario|miniserie|serie|telefilm|anime|"
    r"television series|series|miniseries|documentary|animated|short)\b", re.IGNORECASE)
_WORK_PAREN = re.compile(r"\((?:[^)]*\b)?(film|serie|televisione|documentario|miniserie|anime|"
                         r"television|series|miniseries|documentary)\b[^)]*\)", re.IGNORECASE)

_cache: dict | None = None


def _load_cache() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
    return _cache


def save_cache() -> None:
    if _cache is not None:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")


def _get(url: str) -> dict | None:
    time.sleep(PAUSE_S)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except Exception:
        return None


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _base_title(page_title: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", page_title)


def _year(title: str, desc: str) -> int | None:
    m = re.search(r"\b(19\d{2}|20\d{2})\b", desc) or re.search(r"\b(19\d{2}|20\d{2})\b", title)
    return int(m.group(1)) if m else None


def find_page(label: str, min_year: int) -> dict | None:
    """{'lang','title','desc','year'} della voce Wikipedia dell'opera, o None.

    Solo opere recenti (anno >= min_year, o anno non indicato): un titolo uguale a un
    film di 40 anni fa non deve prenderne le visite. Anno non indicato = scartata.
    Contro: le riedizioni di classici restano senza segnale esterno.
    """
    cache = _load_cache()
    key = f"page2|{min_year}|" + _norm(label)
    if key in cache:
        return cache[key]
    want = _norm(label)
    found = None
    for lang in LANGS:
        for suffix in ("film", "serie televisiva"):
            q = urllib.parse.urlencode({"action": "query", "list": "search", "format": "json",
                                        "srsearch": f"{label} {suffix}", "srlimit": 6})
            res = _get(f"https://{lang}.wikipedia.org/w/api.php?{q}")
            titles = [r["title"] for r in (res or {}).get("query", {}).get("search", [])]
            titles = [t for t in titles if _norm(_base_title(t)) == want]
            if not titles:
                continue
            q = urllib.parse.urlencode({"action": "query", "prop": "description", "format": "json",
                                        "titles": "|".join(titles), "redirects": 1})
            info = _get(f"https://{lang}.wikipedia.org/w/api.php?{q}")
            pages = (info or {}).get("query", {}).get("pages", {})
            descs = {p["title"]: p.get("description", "") for p in pages.values()}
            for t in titles:  # rispetta l'ordine di rilevanza della ricerca
                desc = descs.get(t, "")
                year = _year(t, desc)
                if (_WORK_DESC.search(desc) or _WORK_PAREN.search(t)) and year is not None and year >= min_year:
                    found = {"lang": lang, "title": t, "desc": desc, "year": year}
                    break
            if found:
                break
        if found:
            break
    cache[key] = found
    return found


# ------------------------------------------------------------------------ TMDB
#
# Chiave gratuita (account TMDB -> Impostazioni -> API) in TMDB_API_KEY, nel .env o
# nell'ambiente. Va bene sia la "API Key" v3 sia il "Read Access Token" v4 (JWT).
# Senza chiave tmdb_key() restituisce None e il resto dello script salta TMDB.
# La popolarita' TMDB e' globale, non italiana, e non ha storico: ogni esecuzione ne
# salva uno snapshot in output/cache/tmdb_popularity.csv, cosi' dopo qualche giorno si
# vede la variazione.

TMDB_BASE = "https://api.themoviedb.org/3"
SNAPSHOT_PATH = CACHE_PATH.parent / "tmdb_popularity.csv"


def tmdb_key() -> str | None:
    import os

    try:
        from dotenv import load_dotenv

        load_dotenv(CACHE_PATH.parents[2] / ".env")
    except ImportError:
        pass
    return (os.getenv("TMDB_API_KEY") or "").strip() or None


def _tmdb_get(path: str, params: dict, key: str) -> dict | None:
    params = dict(params)
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if key.startswith("eyJ"):  # token v4
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key
    time.sleep(0.05)
    req = urllib.request.Request(f"{TMDB_BASE}{path}?{urllib.parse.urlencode(params)}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except Exception:
        return None


def find_tmdb(label: str, min_year: int, key: str) -> dict | None:
    """{'id','media_type','title','year','popularity'} del film/serie, o None.

    Primo risultato della ricerca (film e serie) il cui titolo italiano o originale
    coincide con `label` e con anno di uscita >= min_year (stesso criterio di find_page).
    """
    want = _norm(label)
    res = _tmdb_get("/search/multi", {"query": label, "language": "it-IT", "include_adult": "false"}, key)
    for r in (res or {}).get("results", []):
        if r.get("media_type") not in ("movie", "tv"):
            continue
        names = [r.get(f) for f in ("title", "name", "original_title", "original_name") if r.get(f)]
        if want not in {_norm(n) for n in names}:
            continue
        date = r.get("release_date") or r.get("first_air_date") or ""
        if not re.match(r"\d{4}", date) or int(date[:4]) < min_year:
            continue
        return {"id": r["id"], "media_type": r["media_type"], "title": names[0],
                "year": int(date[:4]), "popularity": float(r.get("popularity") or 0.0)}
    return None


def save_snapshot(items: list[dict], today: dt.date) -> None:
    """Aggiunge (data, id, tipo, popolarita') allo storico; una riga per id e giorno."""
    if not items:
        return
    new = pd.DataFrame([{"date": today.isoformat(), "tmdb_id": i["id"], "media_type": i["media_type"],
                         "popularity": i["popularity"]} for i in items])
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if SNAPSHOT_PATH.exists():
        new = pd.concat([pd.read_csv(SNAPSHOT_PATH), new])
    new.drop_duplicates(["date", "tmdb_id", "media_type"], keep="last").to_csv(SNAPSHOT_PATH, index=False)


def previous_popularity(item: dict, today: dt.date, min_days: int) -> float | None:
    """Popolarita' salvata piu' recente tra quelle di almeno `min_days` giorni fa, o None."""
    if not SNAPSHOT_PATH.exists():
        return None
    h = pd.read_csv(SNAPSHOT_PATH)
    h = h[(h["tmdb_id"] == item["id"]) & (h["media_type"] == item["media_type"])
          & (h["date"] <= (today - dt.timedelta(days=min_days)).isoformat())]
    return float(h.sort_values("date").iloc[-1]["popularity"]) if not h.empty else None


def pageviews(page: dict, start: dt.date, end: dt.date) -> pd.Series:
    """Visite giornaliere (Series indicizzata per data, 0 nei giorni mancanti)."""
    cache = _load_cache()
    key = f"pv|{page['lang']}|{page['title']}"
    stored: dict[str, int] = cache.get(key, {})
    days = pd.date_range(start, end)
    fresh_limit = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    missing = [d for d in days if d.date().isoformat() not in stored or d.date().isoformat() >= fresh_limit]
    if missing:
        art = urllib.parse.quote(page["title"].replace(" ", "_"), safe="")
        url = ("https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
               f"{page['lang']}.wikipedia/all-access/user/{art}/daily/"
               f"{missing[0]:%Y%m%d}/{missing[-1]:%Y%m%d}")
        res = _get(url)
        got = {}
        for it in (res or {}).get("items", []):
            ts = it["timestamp"]
            got[f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"] = int(it["views"])
        if res is not None:  # l'API omette i giorni senza visite: valgono 0
            for d in missing:
                stored[d.date().isoformat()] = got.get(d.date().isoformat(), 0)
            cache[key] = stored
    return pd.Series([stored.get(d.date().isoformat(), 0) for d in days], index=days, dtype=float)
