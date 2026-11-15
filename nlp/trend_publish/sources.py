"""
Fonti dei candidati per la scelta degli articoli interni.

Il database (articles_dim + fact_article_score_period) e l'API di WordPress si
iniettano come funzioni, cosi' il modulo non apre connessioni ne' fa rete.
I candidati escono nel formato di link_resolver.choose_article:
{"article_id", "title", "link", "pub_date": date, "scores": [...]}.

Contratto: nlp/trend_publish/README.md, sezione sources.py.
"""

from __future__ import annotations

import html
from datetime import date, datetime
from typing import Callable
from urllib.parse import quote

BASE_WP_POSTS = "https://www.taxidrivers.it/wp-json/wp/v2/posts"


def _nomi(entity: dict) -> list[str]:
    """Titolo e alias dell'entita' (senza vuoti ne' doppioni, ordine stabile)."""
    visti: list[str] = []
    for n in [entity.get("title")] + list(entity.get("aliases") or []):
        if n and n not in visti:
            visti.append(n)
    return visti


def _come_date(valore) -> date | None:
    """date da datetime, date o stringa ISO (le prime 10 cifre)."""
    if valore is None:
        return None
    if isinstance(valore, datetime):
        return valore.date()
    if isinstance(valore, date):
        return valore
    return date.fromisoformat(str(valore)[:10])


def _escape_like(s: str) -> str:
    """Neutralizza i caratteri speciali di LIKE/ILIKE (escape di default: backslash)."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _mancante(x) -> bool:
    """True per None e per NaN (pandas restituisce float("nan") per i NULL)."""
    return x is None or x != x


def candidates_from_db(query_fn: Callable[[str, dict], list[dict]], entity: dict) -> list[dict]:
    """Candidati dal database con una sola query; gli score sono raggruppati per articolo."""
    params: dict = {}
    condizioni: list[str] = []
    for i, nome in enumerate(_nomi(entity)):
        chiave = f"p{i}"
        params[chiave] = f"%{_escape_like(nome)}%"
        condizioni.append(f"a.title ILIKE %({chiave})s")

    sql = (
        "SELECT a.article_id, a.title, a.link, a.published_at AS pub_date,\n"
        "       s.editorial_score, s.active_users\n"
        "FROM articles_dim a\n"
        "LEFT JOIN fact_article_score_period s\n"
        "       ON s.article_id = a.article_id AND s.method_version = 'balanced-v2'\n"
        "WHERE a.status = 'publish'\n"
        f"  AND ({' OR '.join(condizioni) if condizioni else 'FALSE'})\n"
        "ORDER BY a.published_at DESC, a.article_id, s.period_start"
    )

    candidati: dict[int, dict] = {}
    for riga in query_fn(sql, params):
        art = candidati.get(riga["article_id"])
        if art is None:
            art = {
                "article_id": riga["article_id"],
                "title": html.unescape(riga["title"]),
                "link": riga["link"],
                "pub_date": _come_date(riga["pub_date"]),
                "scores": [],
            }
            candidati[riga["article_id"]] = art
        if not _mancante(riga.get("editorial_score")):
            utenti = riga.get("active_users")
            art["scores"].append({
                "editorial_score": float(riga["editorial_score"]),
                "active_users": 0 if _mancante(utenti) else int(utenti),
            })
    return list(candidati.values())


def candidates_from_wp(
    http_get_json: Callable[[str], list[dict]], entity: dict, since: date
) -> list[dict]:
    """Candidati dall'API di WordPress: una ricerca per titolo e per ogni alias."""
    candidati: dict[int, dict] = {}
    for nome in _nomi(entity):
        parametri = [
            ("search", nome),
            ("per_page", "20"),
            ("after", f"{since.isoformat()}T00:00:00"),
            ("_fields", "id,date,link,title"),
        ]
        query = "&".join(f"{k}={quote(v, safe='')}" for k, v in parametri)
        for post in http_get_json(f"{BASE_WP_POSTS}?{query}"):
            if post["id"] in candidati:
                continue
            candidati[post["id"]] = {
                "article_id": post["id"],
                "title": html.unescape(post["title"]["rendered"]),
                "link": post["link"],
                "pub_date": _come_date(post["date"]),
                "scores": [],
            }
    return list(candidati.values())


def merge_candidates(db: list[dict], wp: list[dict]) -> list[dict]:
    """Unione per article_id: vince la riga DB; ordine stabile (prima DB, poi WP)."""
    uniti: dict[int, dict] = {}
    for c in list(db) + list(wp):
        uniti.setdefault(c["article_id"], c)
    return list(uniti.values())
