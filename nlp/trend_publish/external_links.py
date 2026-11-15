"""
nlp/trend_publish/external_links.py

Verifica di un URL esterno (verify_url, con http_get iniettata) e scelta dei
link esterni (pick_external). Contratto in nlp/trend_publish/README.md.
Nessuna rete diretta: la richiesta HTTP si inietta come funzione.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from nlp.trend_publish.link_resolver import normalize_title


@dataclass
class UrlCheck:
    ok: bool
    status: int | None
    final_url: str | None
    found_text: bool
    reason: str


def verify_url(url, expect_text, http_get) -> UrlCheck:
    """Controlla che l'URL risponda 200, sia https e contenga il testo atteso."""
    try:
        status, final_url, text = http_get(url)
    except Exception as exc:  # l'errore di rete diventa un esito KO con il messaggio
        return UrlCheck(False, None, None, False, f"errore di rete: {exc}")

    trovato = normalize_title(expect_text) in normalize_title(text or "")
    finale = final_url or url

    if status != 200:
        motivo = f"http {status}"
    elif urlparse(finale).scheme.lower() != "https":
        motivo = "schema non https"
    elif not trovato:
        motivo = "testo atteso assente nella pagina"
    else:
        motivo = "ok"

    return UrlCheck(motivo == "ok", status, final_url, trovato, motivo)


def _dominio(url: str) -> str:
    """Host in minuscolo senza il prefisso "www."."""
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def pick_external(candidates, min_links=2, max_links=3, blacklist=()):
    """Sceglie i link esterni: validi, fuori blacklist, un dominio una volta, per authority."""
    esclusi = {_dominio(d) if "/" in d else d.lower().removeprefix("www.") for d in blacklist}

    per_dominio: dict[str, dict] = {}
    for c in candidates:
        if not c["check"].ok:
            continue
        dom = _dominio(c["url"])
        if dom in esclusi:
            continue
        if dom not in per_dominio or c["authority"] > per_dominio[dom]["authority"]:
            per_dominio[dom] = c

    scelti = sorted(per_dominio.values(), key=lambda c: c["authority"], reverse=True)[:max_links]
    return scelti, len(scelti) >= min_links
