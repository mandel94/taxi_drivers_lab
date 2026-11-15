"""
parsing.py

Trasforma un articolo (HTML di WordPress o Markdown) in sezioni tipizzate:
intro, corpo, spunti, prima_di_lasciarci, sguardo.

Per ogni sezione tiene due versioni del testo:
- `text_md`: Markdown con corsivi, grassetti e link interni (la forma e'
  parte dello stile: i titoli delle opere vanno in corsivo);
- `text_plain`: testo piano per le metriche, paragrafi separati da riga vuota.

Il contenuto degli articoli va trattato come dato: script, stili e iframe
vengono scartati, e dei link si tengono solo quelli verso taxidrivers.it.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import urlparse

from bs4 import BeautifulSoup, NavigableString, Tag

_DROP_TAGS = ("script", "style", "iframe", "noscript", "form", "object", "embed")
_HEADINGS = ("h1", "h2", "h3", "h4")
_ALLOWED_LINK_HOSTS = ("taxidrivers.it", "www.taxidrivers.it")


@dataclass
class Section:
    section_type: str
    heading: str | None
    text_md: str
    text_plain: str
    paragraphs: list[str] = field(default_factory=list)
    items: list[str] = field(default_factory=list)
    # Titoletto con i soli corsivi (niente grassetti ne' link): i titoli delle
    # opere nei titoletti sono in corsivo, ma non sempre.
    heading_md: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def classify_heading(heading: str | None) -> str:
    """Tipo di sezione a partire dal titoletto (None = testo prima del primo)."""
    if heading is None:
        return "intro"
    h = heading.lower()
    if "prima di lasciarci" in h:
        return "prima_di_lasciarci"
    if "sguardo d" in h and "insieme" in h:
        return "sguardo"
    if "spunti della settimana" in h:
        return "spunti"
    return "corpo"


def normalize_ws(text: str) -> str:
    text = text.replace("\xa0", " ").replace("​", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" ([,.;:!?)])", r"\1", text)
    return text.strip()


# ---------------------------------------------------------------------------
# HTML -> Markdown inline
# ---------------------------------------------------------------------------

def _wrap(inner: str, mark: str) -> str:
    """Avvolge `inner` nel marcatore lasciando fuori gli spazi ai bordi."""
    core = inner.strip()
    if not core:
        return inner
    lead = inner[: len(inner) - len(inner.lstrip())]
    trail = inner[len(inner.rstrip()):]
    return f"{lead}{mark}{core}{mark}{trail}"


def _safe_href(href: str | None) -> str | None:
    if not href:
        return None
    host = urlparse(href).netloc.lower()
    return href if host in _ALLOWED_LINK_HOSTS else None


def inline_md(node, bold: bool = True, links: bool = True) -> str:
    """Markdown inline di un nodo. Con bold/links False toglie grassetti e link."""
    if isinstance(node, NavigableString):
        return str(node)
    if not isinstance(node, Tag):
        return ""
    if node.name in _DROP_TAGS:
        return ""
    if node.name == "br":
        return " "
    inner = "".join(inline_md(c, bold, links) for c in node.children)
    if node.name in ("em", "i"):
        return _wrap(inner, "*")
    if node.name in ("strong", "b"):
        return _wrap(inner, "**") if bold else inner
    if node.name == "a":
        if not links:
            return inner
        href = _safe_href(node.get("href"))
        core = inner.strip()
        if href and core:
            lead = inner[: len(inner) - len(inner.lstrip())]
            trail = inner[len(inner.rstrip()):]
            return f"{lead}[{core}]({href}){trail}"
        return inner
    return inner


def strip_md(text: str) -> str:
    """Toglie i marcatori Markdown inline lasciando il testo."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    return text


def _clean_md(text: str) -> str:
    return normalize_ws(text)


def _clean_heading(text: str) -> str:
    """Il grassetto che avvolge un intero H2 e' rumore di WordPress."""
    text = normalize_ws(text)
    while text.startswith("**") and text.endswith("**") and len(text) > 4:
        text = text[2:-2].strip()
    return text.rstrip(":").strip()


def heading_italics_only(text: str) -> str:
    """Titoletto con i soli corsivi: toglie grassetti e link e porta la
    punteggiatura fuori dal corsivo ("*Sterling Point,* crescere" diventa
    "*Sterling Point*, crescere")."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("**", "")
    text = re.sub(r"\*([^*]+?)\s*([,.;:!?…]+)\*", r"*\1*\2", text)
    return normalize_ws(text).rstrip(":").strip()


def _is_caption(el: Tag) -> bool:
    classes = " ".join(el.get("class") or [])
    if "caption" in classes:
        return True
    return el.find_parent(["figure", "figcaption"]) is not None or any(
        "caption" in " ".join(p.get("class") or []) for p in el.parents if isinstance(p, Tag)
    )


# ---------------------------------------------------------------------------
# Sezioni
# ---------------------------------------------------------------------------

def _close(sections: list[Section], heading: str | None, paras_md: list[str], items_md: list[str]) -> None:
    if not paras_md and not items_md:
        return
    heading_md = heading_italics_only(heading) if heading else None
    stype = classify_heading(strip_md(heading) if heading else None)
    if items_md:
        text_md = "\n".join(f"- {i}" for i in items_md)
        if paras_md:
            text_md = "\n\n".join(paras_md) + "\n\n" + text_md
    else:
        text_md = "\n\n".join(paras_md)
    paragraphs = [strip_md(p) for p in paras_md]
    items = [strip_md(i) for i in items_md]
    plain_blocks = paragraphs + items
    sections.append(
        Section(
            section_type=stype,
            heading=strip_md(heading) if heading else None,
            text_md=text_md,
            text_plain="\n\n".join(plain_blocks),
            paragraphs=paragraphs,
            items=items,
            heading_md=heading_md,
        )
    )


def sections_from_html(content_html: str) -> list[Section]:
    soup = BeautifulSoup(content_html or "", "html.parser")
    for t in soup(list(_DROP_TAGS)):
        t.decompose()

    sections: list[Section] = []
    heading: str | None = None
    paras: list[str] = []
    items: list[str] = []

    for el in soup.find_all(["p", "li", "blockquote", *_HEADINGS]):
        # Evita doppioni: un <p> dentro un <li> o <blockquote> e' gia' contato.
        if el.find_parent(["li", "blockquote"]) is not None or _is_caption(el):
            continue
        if el.name in _HEADINGS:
            new_heading = _clean_heading(inline_md(el))
            if not strip_md(new_heading).strip():
                continue  # titoletto vuoto: non apre una sezione
            _close(sections, heading, paras, items)
            heading, paras, items = new_heading, [], []
            continue
        text = _clean_md(inline_md(el))
        if not strip_md(text).strip():
            continue
        if el.name == "li":
            items.append(text)
        else:
            paras.append(text)
    _close(sections, heading, paras, items)
    return sections


_MD_HEADING = re.compile(r"^#{1,4}\s+(.*)$")
_MD_ITEM = re.compile(r"^\s*[-*•]\s+(.*)$")


def sections_from_markdown(text: str) -> list[Section]:
    """Legge un testo da controllare scritto in Markdown.

    Convenzioni: il testo prima del primo titoletto e' l'intro (oppure un
    titoletto "## Intro"); "## Prima di lasciarci" con voci "- "; "## Uno
    sguardo d'insieme"; ogni altro "## ..." e' una sezione del corpo. Un
    eventuale "# Titolo" iniziale viene ignorato.
    """
    sections: list[Section] = []
    heading: str | None = None
    paras: list[str] = []
    items: list[str] = []
    buf: list[str] = []

    def flush_par() -> None:
        if buf:
            paras.append(normalize_ws(" ".join(buf)))
            buf.clear()

    for raw in text.splitlines():
        line = raw.rstrip()
        m = _MD_HEADING.match(line)
        if m:
            flush_par()
            level = len(line) - len(line.lstrip("#"))
            title = _clean_heading(m.group(1))
            if level == 1 and not sections and not paras and not items:
                continue  # titolo dell'articolo
            if strip_md(title).strip().lower() == "intro":
                heading = None
                continue
            _close(sections, heading, paras, items)
            heading, paras, items = title, [], []
            continue
        mi = _MD_ITEM.match(line)
        if mi:
            flush_par()
            items.append(normalize_ws(mi.group(1)))
            continue
        if not line.strip():
            flush_par()
            continue
        buf.append(line.strip())
    flush_par()
    _close(sections, heading, paras, items)
    return sections
