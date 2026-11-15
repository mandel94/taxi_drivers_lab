"""
Fase 1 di trend_publish: correzione grammaticale del testo del Trend Radar.

Il giudizio (cosa e' un errore) lo danno i sottoagenti della skill; questo
modulo controlla che ogni modifica proposta rispetti le regole del contratto
(README.md) e la applica senza toccare altro. Le funzioni sono pure: nessuna
rete, nessun database, nessun argomento viene modificato.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

ALLOWED_CATEGORIES = frozenset({
    "ortografia", "accento", "apostrofo", "doppie", "concordanza",
    "tempo_verbale", "congiuntivo", "preposizione", "articolo", "refuso",
})

# Massimo di parole diverse tra frammento originale e sostituzione.
MAX_PAROLE_DIVERSE = 4

_RE_LINK_MD = re.compile(r"\[[^\]]*\]\([^)]*\)")
_RE_URL = re.compile(r"https?://[^\s)\]]+")


@dataclass
class Edit:
    """Una modifica proposta: sostituire `original` con `replacement`."""

    id: str
    original: str
    replacement: str
    category: str
    reason: str


@dataclass
class Rejection:
    """Una modifica rifiutata, con il motivo esatto del rifiuto."""

    edit: Edit
    reason: str


def _posizioni(text: str, frammento: str) -> list[int]:
    """Posizioni (anche sovrapposte) in cui `frammento` compare in `text`."""
    if not frammento:
        return []
    out = []
    i = text.find(frammento)
    while i != -1:
        out.append(i)
        i = text.find(frammento, i + 1)
    return out


def _zone_protette(text: str, protected) -> list[tuple[int, int]]:
    """Intervalli [inizio, fine) da non toccare: stringhe protette, link Markdown, URL."""
    zone: list[tuple[int, int]] = []
    for s in protected:
        for i in _posizioni(text, s):
            zone.append((i, i + len(s)))
    for m in _RE_LINK_MD.finditer(text):
        zone.append((m.start(), m.end()))
    for m in _RE_URL.finditer(text):
        # la punteggiatura finale non fa parte dell'URL
        fine = m.end()
        while fine > m.start() and text[fine - 1] in ".,;:!?":
            fine -= 1
        zone.append((m.start(), fine))
    return zone


def _sovrapposti(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _parole_diverse(original: str, replacement: str) -> int:
    """Numero di parole diverse tra i due frammenti (confronto per parole)."""
    a, b = original.split(), replacement.split()
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    totale = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            totale += max(i2 - i1, j2 - j1)
    return totale


def validate_edits(text, edits, protected=()):
    """Divide gli edit in accettati (ordine di input) e rifiutati, con il motivo esatto."""
    zone = _zone_protette(text, protected)
    accepted: list[Edit] = []
    rejected: list[Rejection] = []
    intervalli: list[tuple[int, int]] = []  # in parallelo ad `accepted`

    for e in edits:
        if e.category not in ALLOWED_CATEGORIES:
            rejected.append(Rejection(e, "categoria non ammessa"))
            continue
        pos = _posizioni(text, e.original)
        if not pos:
            rejected.append(Rejection(e, "frammento assente"))
            continue
        if len(pos) > 1:
            rejected.append(Rejection(e, "frammento ambiguo"))
            continue
        if e.original == e.replacement:
            rejected.append(Rejection(e, "nessuna modifica"))
            continue
        iv = (pos[0], pos[0] + len(e.original))
        if any(_sovrapposti(iv, z) for z in zone):
            rejected.append(Rejection(e, "tocca una zona protetta"))
            continue
        if _parole_diverse(e.original, e.replacement) > MAX_PAROLE_DIVERSE:
            rejected.append(Rejection(e, "modifica troppo estesa"))
            continue
        if any(_sovrapposti(iv, altro) for altro in intervalli):
            rejected.append(Rejection(e, "sovrapposto a un'altra modifica"))
            continue
        accepted.append(e)
        intervalli.append(iv)
    return accepted, rejected


def _intervalli_edit(text: str, accepted) -> list[tuple[int, int, Edit]]:
    """Posizioni degli edit nel testo originale (prima occorrenza), in ordine di posizione."""
    out = []
    for e in accepted:
        i = text.find(e.original) if e.original else -1
        if i != -1:
            out.append((i, i + len(e.original), e))
    out.sort(key=lambda t: t[0])
    return out


def apply_edits(text, accepted):
    """Applica tutte le modifiche accettate alle posizioni trovate nel testo originale."""
    out = text
    # da destra a sinistra, cosi' le posizioni a sinistra restano valide
    for inizio, fine, e in reversed(_intervalli_edit(text, accepted)):
        out = out[:inizio] + e.replacement + out[fine:]
    return out


def only_listed_changes(original, corrected, accepted):
    """True solo se ogni differenza tra `original` e `corrected` cade dentro un edit accettato."""
    if corrected == apply_edits(original, accepted):
        return True
    intervalli = [(s, f) for s, f, _ in _intervalli_edit(original, accepted)]
    sm = difflib.SequenceMatcher(None, original, corrected, autojunk=False)
    for tag, i1, i2, _j1, _j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        if not any(s <= i1 and i2 <= f for s, f in intervalli):
            return False
    return True


def _cella(s: str) -> str:
    """Testo adatto a una cella di tabella Markdown: niente a capo, pipe escapato."""
    return " ".join(str(s).split()).replace("|", "\\|")


def render_report(accepted, rejected, doubts):
    """Rapporto Markdown delle correzioni, dei rifiuti e dei dubbi."""
    righe = [
        "# Correzioni grammaticali",
        "",
        f"{len(accepted)} correzioni applicate, {len(rejected)} rifiutate, "
        f"{len(doubts)} dubbi non toccati",
        "",
    ]

    if not accepted:
        righe += ["Nessuna correzione necessaria.", ""]
    else:
        per_categoria: dict[str, list[Edit]] = {}
        for e in accepted:
            per_categoria.setdefault(e.category, []).append(e)
        righe.append("Per categoria:")
        righe.append("")
        for cat, lista in per_categoria.items():
            righe.append(f"- {cat}: {len(lista)}")
        righe.append("")
        righe.append("| Prima | Dopo | Categoria | Motivo |")
        righe.append("| --- | --- | --- | --- |")
        for cat, lista in per_categoria.items():
            for e in lista:
                righe.append(
                    f"| {_cella(e.original)} | {_cella(e.replacement)} | "
                    f"{_cella(cat)} | {_cella(e.reason)} |"
                )
        righe.append("")

    if rejected:
        righe += ["## Rifiutate", ""]
        for r in rejected:
            e = r.edit
            righe.append(
                f"- {_testo_riga(e.original)} -> {_testo_riga(e.replacement)} "
                f"({e.category}): {r.reason}"
            )
        righe.append("")

    if doubts:
        righe += ["## Dubbi (non modificati)", ""]
        for d in doubts:
            righe.append(f"- {_testo_riga(d['fragment'])}: {_testo_riga(d['note'])}")
        righe.append("")

    return "\n".join(righe).rstrip("\n") + "\n"


def _testo_riga(s: str) -> str:
    """Testo su una sola riga (per gli elenchi del rapporto)."""
    return " ".join(str(s).split())
