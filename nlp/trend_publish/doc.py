"""
Modello del testo di un Trend Radar.

Legge il testo incollato (righe separate da "\\n") e lo divide in sezioni:
intro, sezioni con titolo, "Prima di lasciarci" (elenco) e "Uno sguardo
d'insieme". Offre anche il Markdown di lavoro (e il suo inverso) e i blocchi di
testo semplice. Modulo puro: nessuna rete, nessun database.

Contratto: nlp/trend_publish/README.md, sezione doc.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Una riga titolo non finisce con uno di questi caratteri e ha al massimo
# MAX_PAROLE_TITOLO parole.
_FINALI_NON_TITOLO = ".!?:"
MAX_PAROLE_TITOLO = 14

TITOLO_PDL = "Prima di lasciarci"
_PDL_NORMALIZZATO = "prima di lasciarci"
_SGUARDO_NORMALIZZATO = "uno sguardo d'insieme"


@dataclass
class Section:
    """Una sezione del testo: kind e' 'intro', 'section', 'pdl' o 'sguardo'."""

    kind: str
    title: str | None = None
    paragraphs: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)  # solo per 'pdl'


@dataclass
class Draft:
    """Il testo intero come lista ordinata di sezioni."""

    sections: list[Section] = field(default_factory=list)

    def to_markdown(self) -> str:
        """Markdown di lavoro: intro, poi '## titolo' e paragrafi; per 'pdl' l'elenco '- item'."""
        blocchi: list[str] = []
        for s in self.sections:
            if s.kind != "intro":
                blocchi.append(f"## {s.title}")
            blocchi.extend(s.paragraphs)
            if s.items:
                blocchi.append("\n".join(f"- {item}" for item in s.items))
        if not blocchi:
            return ""
        return "\n\n".join(blocchi) + "\n"

    def plain_blocks(self) -> list[str]:
        """Paragrafi e item in ordine, senza titoli."""
        blocchi: list[str] = []
        for s in self.sections:
            blocchi.extend(s.paragraphs)
            blocchi.extend(s.items)
        return blocchi


def _canonica(riga: str) -> str:
    """Forma di confronto di un titolo: senza due punti finali, minuscolo, apostrofo dritto."""
    r = riga.strip().rstrip(":").strip().casefold()
    r = r.replace("’", "'").replace("‘", "'").replace("ʼ", "'")
    return " ".join(r.split())


def _is_pdl(riga: str) -> bool:
    return _canonica(riga) == _PDL_NORMALIZZATO


def _is_sguardo(riga: str) -> bool:
    return _canonica(riga) == _SGUARDO_NORMALIZZATO


def _sembra_titolo(riga: str) -> bool:
    """Riga senza . ! ? : finale e con al massimo 14 parole."""
    return riga[-1] not in _FINALI_NON_TITOLO and len(riga.split()) <= MAX_PAROLE_TITOLO


def _righe_non_vuote(text: str) -> list[str]:
    """Righe con strip agli estremi; le righe vuote (anche ripetute) si scartano."""
    righe = (r.strip() for r in re.split(r"\r\n|\r|\n", text))
    return [r for r in righe if r]


def _nuova_sezione_da_titolo(titolo: str) -> Section | None:
    """Sezione 'pdl' o 'sguardo' se il titolo e' uno di quelli speciali, altrimenti None."""
    if _is_pdl(titolo):
        return Section(kind="pdl", title=TITOLO_PDL)
    if _is_sguardo(titolo):
        return Section(kind="sguardo", title=titolo.strip())
    return None


def parse_draft(text: str) -> Draft:
    """Legge il testo incollato e lo divide in sezioni (vedi README)."""
    righe = _righe_non_vuote(text)
    sezioni = [Section(kind="intro", title=None)]
    corrente = sezioni[0]

    for i, riga in enumerate(righe):
        # Dopo "Prima di lasciarci" ogni riga e' un item, fino allo sguardo d'insieme.
        if corrente.kind == "pdl" and not _is_sguardo(riga):
            corrente.items.append(riga)
            continue

        speciale = _nuova_sezione_da_titolo(riga)
        if speciale is not None:
            sezioni.append(speciale)
            corrente = speciale
        elif _sembra_titolo(riga) and i + 1 < len(righe):
            corrente = Section(kind="section", title=riga)
            sezioni.append(corrente)
        else:
            corrente.paragraphs.append(riga)

    return Draft(sections=sezioni)


def markdown_to_draft(md: str) -> Draft:
    """Inverso di Draft.to_markdown: '## ' apre una sezione, '- ' e' un item di 'pdl'."""
    sezioni = [Section(kind="intro", title=None)]
    corrente = sezioni[0]

    for riga in _righe_non_vuote(md):
        if riga.startswith("## "):
            titolo = riga[3:].strip()
            corrente = _nuova_sezione_da_titolo(titolo) or Section(kind="section", title=titolo)
            sezioni.append(corrente)
        elif corrente.kind == "pdl" and riga.startswith("- "):
            corrente.items.append(riga[2:].strip())
        else:
            corrente.paragraphs.append(riga)

    return Draft(sections=sezioni)
