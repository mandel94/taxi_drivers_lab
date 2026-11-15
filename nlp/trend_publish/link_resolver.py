"""
Scelta degli articoli interni da linkare nel Trend Radar.

Estrae i titoli tra virgolette dai titoli degli articoli, li confronta con
l'entita' cercata (titolo, alias, stagione) e sceglie l'articolo secondo le
regole del contratto: recensione recente, score massimo, fallback sul piu'
recente. Funzioni pure: nessuna rete, nessun database.

Contratto: nlp/trend_publish/README.md, sezione link_resolver.py.
"""

from __future__ import annotations

import html
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urlsplit

# Caratteri che aprono o chiudono un titolo tra virgolette (dopo html.unescape).
_VIRGOLETTE = "‘’“”'"
_APOSTROFI = "'’"

# Rango per lo spareggio del fallback a parita' di data: review, poi serie-tv.
_RANGO_SEZIONE = {"review": 2, "serie-tv": 1}


@dataclass
class Choice:
    """Esito della scelta di un articolo; alternatives ha fino a 3 altri candidati."""

    article_id: int | None
    link: str | None
    title: str | None
    reason: str
    score: float | None
    alternatives: list[dict]


def normalize_title(s: str) -> str:
    """Minuscolo, senza accenti, solo [a-z0-9] separati da un unico spazio."""
    s = html.unescape(s or "").casefold()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]", " ", s).split())


def quoted_titles(article_title: str) -> list[tuple[str, int | None]]:
    """Titoli tra virgolette di un titolo di articolo: [(titolo normalizzato, stagione | None)]."""
    s = html.unescape(article_title or "")
    n = len(s)

    # Posizioni dei caratteri che sono davvero virgolette.
    posizioni: list[int] = []
    for i, ch in enumerate(s):
        if ch not in _VIRGOLETTE:
            continue
        prima = s[i - 1] if i > 0 else ""
        dopo = s[i + 1] if i + 1 < n else ""
        # Apostrofo dentro una parola (l'essere, Don't): non e' una virgoletta.
        if prima.isalnum() and dopo.isalnum():
            continue
        # Anno abbreviato ('27 seguito da un non-alfanumerico): non e' una virgoletta.
        if ch in _APOSTROFI:
            due = s[i + 1:i + 3]
            if len(due) == 2 and due.isdigit() and not s[i + 3:i + 4].isalnum():
                continue
        posizioni.append(i)

    # Le virgolette si appaiono in sequenza: 1a con 2a, 3a con 4a, ...
    risultato: list[tuple[str, int | None]] = []
    for k in range(0, len(posizioni) - 1, 2):
        a, b = posizioni[k], posizioni[k + 1]
        dentro = s[a + 1:b]
        stagione: int | None = None
        titolo = dentro

        # Numero di stagione che chiude il titolo dentro le virgolette ("Black Doves 2")...
        m = re.match(r"^(.*\S)\s+(\d{1,3})\s*$", dentro, re.S)
        if m:
            titolo, stagione = m.group(1), int(m.group(2))
        else:
            # ... oppure subito dopo la virgoletta di chiusura ("'Black Doves' 2: ...").
            # Un numero di 4 cifre non e' mai una stagione.
            m = re.match(r"\s*(\d{1,3})(?!\w)", s[b + 1:])
            if m:
                stagione = int(m.group(1))

        normalizzato = normalize_title(titolo)
        if normalizzato:
            risultato.append((normalizzato, stagione))
    return risultato


def _nomi_entita(entity: dict) -> set[str]:
    """Titolo e alias dell'entita', normalizzati."""
    nomi = [entity.get("title") or ""] + list(entity.get("aliases") or [])
    return {n for n in (normalize_title(x) for x in nomi) if n}


def matches_entity(article_title: str, entity: dict) -> bool:
    """True se un titolo tra virgolette e' uguale (mai sottostringa) al titolo o a un alias.

    Se l'entita' ha una stagione e l'articolo ne ha una diversa: False;
    se l'articolo non ha numero di stagione: True.
    """
    nomi = _nomi_entita(entity)
    stagione_attesa = entity.get("season")
    for titolo, stagione in quoted_titles(article_title):
        if titolo not in nomi:
            continue
        if isinstance(stagione_attesa, int) and stagione is not None and stagione != stagione_attesa:
            continue
        return True
    return False


def _segmenti(link: str) -> list[str]:
    return [p for p in urlsplit(link or "").path.split("/") if p]


def section_of(link: str) -> str:
    """Primo segmento del percorso dopo l'id (.../564645/serie-tv/x.html -> serie-tv)."""
    segmenti = _segmenti(link)
    for i, seg in enumerate(segmenti):
        if seg.isdigit():
            return segmenti[i + 1] if i + 1 < len(segmenti) else ""
    return ""


def is_si_fara(link: str) -> bool:
    """True se 'si-fara' e' un segmento del percorso."""
    return "si-fara" in _segmenti(link)


def eligible_score(scores: list[dict], min_users: int = 15) -> float | None:
    """Massimo editorial_score tra le settimane con active_users >= min_users; None se nessuna."""
    validi = [
        s["editorial_score"]
        for s in scores
        if s.get("editorial_score") is not None
        and s.get("active_users") is not None
        and s["active_users"] >= min_users
    ]
    return max(validi) if validi else None


def _alternativa(c: dict, min_users: int) -> dict:
    return {
        "article_id": c["article_id"],
        "title": c["title"],
        "link": c["link"],
        "score": eligible_score(c["scores"], min_users),
    }


def choose_article(
    entity: dict,
    candidates: list[dict],
    today: date,
    min_users: int = 15,
    recent_days: int = 14,
) -> Choice:
    """Sceglie l'articolo da linkare per l'entita' (regole in ordine, vedi README)."""
    corrispondenti = [c for c in candidates if matches_entity(c["title"], entity)]
    if not corrispondenti:
        return Choice(None, None, None, "nessun articolo", None, [])

    punteggi = {id(c): eligible_score(c["scores"], min_users) for c in corrispondenti}

    scelto: dict | None = None
    motivo = ""

    # 1. Recensione recente senza score: vince la piu' recente.
    soglia = today - timedelta(days=recent_days)
    recenti = [
        c for c in corrispondenti
        if section_of(c["link"]) == "review"
        and c["pub_date"] >= soglia
        and punteggi[id(c)] is None
    ]
    if recenti:
        scelto = max(recenti, key=lambda c: c["pub_date"])
        motivo = "recensione recente senza score"

    # 2. Score massimo (a parita' la pub_date piu' recente).
    if scelto is None:
        con_score = [c for c in corrispondenti if punteggi[id(c)] is not None]
        if con_score:
            scelto = max(con_score, key=lambda c: (punteggi[id(c)], c["pub_date"]))
            motivo = "score massimo"

    # 3. Fallback: il piu' recente (a parita' review, poi serie-tv).
    if scelto is None:
        scelto = max(
            corrispondenti,
            key=lambda c: (c["pub_date"], _RANGO_SEZIONE.get(section_of(c["link"]), 0)),
        )
        motivo = "nessun articolo sopra soglia: il più recente"

    altri = [c for c in corrispondenti if c is not scelto]
    # Score decrescente, None in fondo; sort stabile.
    altri.sort(key=lambda c: (punteggi[id(c)] is None, -(punteggi[id(c)] or 0.0)))
    alternatives = [_alternativa(c, min_users) for c in altri[:3]]

    return Choice(
        article_id=scelto["article_id"],
        link=scelto["link"],
        title=scelto["title"],
        reason=motivo,
        score=punteggi[id(scelto)],
        alternatives=alternatives,
    )


def choose_si_fara(entity: dict, candidates: list[dict]) -> Choice:
    """Articolo 'Si farà' dell'entita': ignora la stagione, vince la pub_date piu' recente."""
    nomi = _nomi_entita(entity)
    trovati = [
        c for c in candidates
        if is_si_fara(c["link"]) and any(t in nomi for t, _ in quoted_titles(c["title"]))
    ]
    if not trovati:
        return Choice(None, None, None, "nessun articolo Si farà", None, [])
    scelto = max(trovati, key=lambda c: c["pub_date"])
    return Choice(
        article_id=scelto["article_id"],
        link=scelto["link"],
        title=scelto["title"],
        reason="articolo Si farà",
        score=eligible_score(scelto["scores"]),
        alternatives=[],
    )
