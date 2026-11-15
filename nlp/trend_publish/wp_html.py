"""
nlp/trend_publish/wp_html.py

Da Draft a HTML dell'editor classico di WordPress (to_wp_html) e formato
"HTML Format" degli appunti di Windows (build_cf_html).
Contratto in nlp/trend_publish/README.md. Solo libreria standard, nessuna rete.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # solo per i tipi: evita dipendenze circolari a runtime
    from nlp.trend_publish.doc import Draft

# Prefisso e suffisso del paragrafo del sito.
_P_OPEN = '<p><span style="font-weight: 400;">'
_P_CLOSE = "</span></p>"

# Titolo canonico della sezione elenco.
_TITOLO_PDL = "Prima di lasciarci"

# Token del Markdown inline, in ordine di priorita': link, grassetto-corsivo,
# grassetto, corsivo.
_INLINE = re.compile(
    r"\[(?P<lt>[^\]]*)\]\((?P<url>[^)\s]*)\)"
    r"|\*\*\*(?P<bi>.+?)\*\*\*"
    r"|\*\*(?P<b>.+?)\*\*"
    r"|\*(?P<i>[^*]+?)\*"
)


def _escape_testo(s: str) -> str:
    """Escape di & < > (le virgolette tipografiche restano invariate)."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _escape_url(u: str) -> str:
    """Escape di un URL dentro l'attributo href (& diventa &amp;)."""
    return _escape_testo(u).replace('"', "&quot;")


def _inline(s: str) -> str:
    """Converte il Markdown inline in HTML.

    Prima si tokenizza il Markdown, poi si esegue l'escape del solo testo,
    cosi' i tag generati non vengono escapati.
    """
    out: list[str] = []
    pos = 0
    for m in _INLINE.finditer(s):
        out.append(_escape_testo(s[pos:m.start()]))
        if m.group("lt") is not None:
            out.append(f'<a href="{_escape_url(m.group("url"))}">{_inline(m.group("lt"))}</a>')
        elif m.group("bi") is not None:
            out.append(f"<em><strong>{_inline(m.group('bi'))}</strong></em>")
        elif m.group("b") is not None:
            out.append(f"<strong>{_inline(m.group('b'))}</strong>")
        else:
            out.append(f"<em>{_inline(m.group('i'))}</em>")
        pos = m.end()
    out.append(_escape_testo(s[pos:]))
    return "".join(out)


def to_wp_html(draft: "Draft") -> str:
    """HTML dell'editor classico di WordPress, un blocco per riga."""
    righe: list[str] = []
    for sez in draft.sections:
        if sez.kind == "pdl":
            righe.append(f"<h2><strong>{_TITOLO_PDL}</strong></h2>")
            voci = [f"<li>{_inline(i.strip())}</li>" for i in sez.items if i.strip()]
            if voci:
                righe.append("<ul>" + "".join(voci) + "</ul>")
            continue
        if sez.title and sez.title.strip():
            righe.append(f"<h2><strong>{_inline(sez.title.strip())}</strong></h2>")
        for p in sez.paragraphs:
            if p.strip():
                righe.append(f"{_P_OPEN}{_inline(p.strip())}{_P_CLOSE}")
    return "\n".join(righe)


def build_cf_html(fragment: str) -> bytes:
    """Formato "HTML Format" degli appunti di Windows (offset in byte UTF-8)."""
    prefisso = "<html><body><!--StartFragment-->"
    suffisso = "<!--EndFragment--></body></html>"

    def intestazione(sh: int, eh: int, sf: int, ef: int) -> str:
        return (
            "Version:0.9\r\n"
            f"StartHTML:{sh:08d}\r\n"
            f"EndHTML:{eh:08d}\r\n"
            f"StartFragment:{sf:08d}\r\n"
            f"EndFragment:{ef:08d}\r\n"
        )

    # Le cifre hanno larghezza fissa: la lunghezza dell'intestazione e' nota in anticipo.
    start_html = len(intestazione(0, 0, 0, 0).encode("utf-8"))
    start_fragment = start_html + len(prefisso.encode("utf-8"))
    end_fragment = start_fragment + len(fragment.encode("utf-8"))
    end_html = end_fragment + len(suffisso.encode("utf-8"))

    testo = intestazione(start_html, end_html, start_fragment, end_fragment) + prefisso + fragment + suffisso
    return testo.encode("utf-8")
