"""
Fase 2 di trend_publish: link interni, corsivo sui titoli e link esterni.

Lavora sul `Draft` di doc.py (sezioni, paragrafi, item) con il Markdown
dell'editor: `[***Titolo***](url)` per i link interni alla prima citazione,
`*Titolo*` per il corsivo, `[ancora](url)` per i link esterni. Le funzioni
sono pure: il `Draft` in input non cambia, ne viene restituito uno nuovo.
Nessuna rete, nessun database.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass

from nlp.trend_publish.doc import Draft, Section  # noqa: F401  (Section per chiarezza dei tipi)

_RE_LINK_MD = re.compile(r"\[[^\]]*\]\([^)]*\)")
_RE_CORSIVO = re.compile(r"\*+[^*\n]+\*+")


@dataclass
class LinkSpec:
    """Un link interno da inserire: `surface` diventa un link verso `url`."""

    surface: str
    url: str
    scope: str = "body"  # 'body' | 'pdl' | 'any'


def _spazi_link(text: str) -> list[tuple[int, int]]:
    """Intervalli [inizio, fine) occupati da link Markdown."""
    return [(m.start(), m.end()) for m in _RE_LINK_MD.finditer(text)]


def _occorrenze(text: str, needle: str, bloccati) -> list[int]:
    """Posizioni (non sovrapposte) di `needle` che non toccano gli intervalli `bloccati`."""
    if not needle:
        return []
    out = []
    i = text.find(needle)
    while i != -1:
        fine = i + len(needle)
        if not any(i < b1 and a1 < fine for a1, b1 in bloccati):
            out.append(i)
        i = text.find(needle, fine)
    return out


def _posti_ammessi(draft: Draft, scope: str):
    """Elenco (indice sezione, campo, indice, testo) dove un link con questo scope e' ammesso."""
    posti = []
    for si, s in enumerate(draft.sections):
        if scope == "body":
            if s.kind == "section":
                posti += [(si, "paragraphs", pi, t) for pi, t in enumerate(s.paragraphs)]
        elif scope == "pdl":
            if s.kind == "pdl":
                posti += [(si, "items", ii, t) for ii, t in enumerate(s.items)]
        elif scope == "any":
            posti += [(si, "paragraphs", pi, t) for pi, t in enumerate(s.paragraphs)]
            posti += [(si, "items", ii, t) for ii, t in enumerate(s.items)]
    return posti


def apply_internal_links(draft, specs):
    """Link interni alla prima occorrenza utile di ogni surface. Ritorna (Draft, rapporto)."""
    new = copy.deepcopy(draft)
    usati: set[str] = set()
    rapporto: list[dict] = []

    for spec in specs:
        voce = {"surface": spec.surface, "url": spec.url, "applied": False,
                "where": None, "reason": ""}
        rapporto.append(voce)

        if spec.url in usati:
            voce["reason"] = "url gia' usato"
            continue

        trovato_in_link = False
        for si, campo, idx, testo in _posti_ammessi(new, spec.scope):
            if not spec.surface or spec.surface not in testo:
                continue
            occ = _occorrenze(testo, spec.surface, _spazi_link(testo))
            if not occ:
                trovato_in_link = True
                continue
            i = occ[0]
            nuovo = (testo[:i] + f"[***{spec.surface}***]({spec.url})"
                     + testo[i + len(spec.surface):])
            getattr(new.sections[si], campo)[idx] = nuovo
            usati.add(spec.url)
            voce["applied"] = True
            voce["where"] = f"{si}/{idx}"
            voce["reason"] = "applicato"
            break
        else:
            voce["reason"] = ("surface solo dentro un link esistente" if trovato_in_link
                              else "surface assente")
    return new, rapporto


def _corsivo_testo(text: str, surfaces) -> str:
    """Avvolge in *...* le occorrenze delle surface fuori da link e corsivi, senza annidare."""
    for surface in surfaces:
        bloccati = _spazi_link(text) + [(m.start(), m.end()) for m in _RE_CORSIVO.finditer(text)]
        occ = _occorrenze(text, surface, bloccati)
        for i in reversed(occ):
            text = text[:i] + f"*{surface}*" + text[i + len(surface):]
    return text


def italicize_titles(draft, surfaces):
    """Corsivo su ogni occorrenza delle surface (titoli di sezione compresi), le piu' lunghe prima."""
    ordinate = sorted(surfaces, key=len, reverse=True)
    new = copy.deepcopy(draft)
    for s in new.sections:
        if s.title is not None:
            s.title = _corsivo_testo(s.title, ordinate)
        s.paragraphs = [_corsivo_testo(p, ordinate) for p in s.paragraphs]
        s.items = [_corsivo_testo(i, ordinate) for i in s.items]
    return new


def apply_external_links(draft, picks):
    """Link esterni `[ancora](url)`: l'ancora deve comparire esattamente una volta nei paragrafi."""
    new = copy.deepcopy(draft)
    rapporto: list[dict] = []

    for pick in picks:
        anchor, url = pick["anchor"], pick["url"]
        voce = {"surface": anchor, "anchor": anchor, "url": url, "applied": False,
                "where": None, "reason": ""}
        rapporto.append(voce)

        trovate = []  # (indice sezione, indice paragrafo, posizione)
        for si, s in enumerate(new.sections):
            if s.kind != "section":
                continue
            for pi, testo in enumerate(s.paragraphs):
                for i in _occorrenze(testo, anchor, _spazi_link(testo)):
                    trovate.append((si, pi, i))

        if not trovate:
            voce["reason"] = "ancora assente"
            continue
        if len(trovate) > 1:
            voce["reason"] = "ancora ambigua"
            continue

        si, pi, i = trovate[0]
        testo = new.sections[si].paragraphs[pi]
        new.sections[si].paragraphs[pi] = (testo[:i] + f"[{anchor}]({url})"
                                           + testo[i + len(anchor):])
        voce["applied"] = True
        voce["where"] = f"{si}/{pi}"
        voce["reason"] = "applicato"
    return new, rapporto
