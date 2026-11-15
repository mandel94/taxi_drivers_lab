"""
tests/test_trend_publish_html.py

nlp/trend_publish/wp_html.py: da Draft a HTML dell'editor classico di WordPress
(to_wp_html) e formato "HTML Format" degli appunti di Windows (build_cf_html).
Contratto in nlp/trend_publish/README.md. Niente rete, niente database.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_trend_publish_html.py
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup  # noqa: E402

from nlp.trend_publish.doc import Draft, Section  # noqa: E402
from nlp.trend_publish.wp_html import build_cf_html, to_wp_html  # noqa: E402

URL_BD = "https://www.taxidrivers.it/564645/serie-tv/black-doves-2.html"
URL_LB = "https://www.taxidrivers.it/551853/review/look-back.html"

P_OPEN = '<p><span style="font-weight: 400;">'
P_CLOSE = "</span></p>"


def _p(testo: str) -> str:
    return f"{P_OPEN}{testo}{P_CLOSE}"


def _draft_completo() -> Draft:
    return Draft(
        sections=[
            Section(
                kind="intro",
                title=None,
                paragraphs=["Prima riga di intro.", "Seconda riga di intro."],
                items=[],
            ),
            Section(
                kind="section",
                title="Black Doves, quando lo spy thriller si unisce al dramma famigliare",
                paragraphs=[
                    f"Con [***Black Doves***]({URL_BD}) la serie unisce *spy thriller* "
                    "e **dramma** famigliare, con un [sito esterno](https://example.com/x) a margine."
                ],
                items=[],
            ),
            Section(
                kind="section",
                title="*Godzilla Minus Zero*, l’elaborazione collettiva di un lutto",
                paragraphs=["Un film che parla di lutto."],
                items=[],
            ),
            Section(
                kind="pdl",
                title="Prima di lasciarci",
                paragraphs=[],
                items=[
                    f"Recuperiamo [*Look Back*]({URL_LB}) di Fujimoto.",
                    "Aspettiamo la nuova stagione.",
                ],
            ),
            Section(
                kind="sguardo",
                title="Uno sguardo d’insieme",
                paragraphs=["La settimana racconta un pubblico che cerca emozioni."],
                items=[],
            ),
        ]
    )


def _draft_con_paragrafi(*paragrafi: str) -> Draft:
    return Draft(
        sections=[
            Section(kind="intro", title=None, paragraphs=["Intro."], items=[]),
            Section(kind="section", title="Titolo", paragraphs=list(paragrafi), items=[]),
        ]
    )


def _righe(html: str) -> list[str]:
    return [r for r in html.splitlines() if r.strip()]


# --------------------------------------------------------------------------
# to_wp_html: blocchi chiave
# --------------------------------------------------------------------------


def test_paragrafi_e_intro_hanno_il_blocco_p_span():
    righe = _righe(to_wp_html(_draft_completo()))
    assert _p("Prima riga di intro.") in righe
    assert _p("Seconda riga di intro.") in righe
    assert _p("Un film che parla di lutto.") in righe
    assert _p("La settimana racconta un pubblico che cerca emozioni.") in righe


def test_titolo_di_sezione_e_h2_strong():
    righe = _righe(to_wp_html(_draft_completo()))
    assert (
        "<h2><strong>Black Doves, quando lo spy thriller si unisce al dramma famigliare</strong></h2>"
        in righe
    )
    assert "<h2><strong>Uno sguardo d’insieme</strong></h2>" in righe


def test_corsivo_nel_titolo_resta_em_dentro_strong():
    righe = _righe(to_wp_html(_draft_completo()))
    assert (
        "<h2><strong><em>Godzilla Minus Zero</em>, l’elaborazione collettiva di un lutto</strong></h2>"
        in righe
    )


def test_prima_di_lasciarci_h2_poi_ul_con_li_su_una_riga():
    righe = _righe(to_wp_html(_draft_completo()))
    assert "<h2><strong>Prima di lasciarci</strong></h2>" in righe
    i = righe.index("<h2><strong>Prima di lasciarci</strong></h2>")
    ul = righe[i + 1]
    assert ul.startswith("<ul><li>") and ul.endswith("</li></ul>")
    assert ul.count("<li>") == 2 and ul.count("</li>") == 2
    assert "Aspettiamo la nuova stagione.</li>" in ul


def test_link_grassetto_corsivo_diventa_a_em_strong():
    html = to_wp_html(_draft_completo())
    assert f'<a href="{URL_BD}"><em><strong>Black Doves</strong></em></a>' in html


def test_link_con_corsivo_dentro_il_testo_nel_pdl():
    # Assunzione sul contratto: il testo di un link e' elaborato come inline,
    # quindi [*Look Back*](u) -> <a href="u"><em>Look Back</em></a> (come sul sito).
    html = to_wp_html(_draft_completo())
    assert f'<a href="{URL_LB}"><em>Look Back</em></a>' in html


def test_link_normale_corsivo_e_grassetto_inline():
    html = to_wp_html(_draft_completo())
    assert '<a href="https://example.com/x">sito esterno</a>' in html
    assert "<em>spy thriller</em>" in html
    assert "<strong>dramma</strong>" in html


def test_paragrafo_con_link_corsivo_e_grassetto_stringa_esatta():
    righe = _righe(to_wp_html(_draft_completo()))
    atteso = _p(
        f'Con <a href="{URL_BD}"><em><strong>Black Doves</strong></em></a> la serie unisce '
        "<em>spy thriller</em> e <strong>dramma</strong> famigliare, con un "
        '<a href="https://example.com/x">sito esterno</a> a margine.'
    )
    assert atteso in righe


def test_un_blocco_per_riga_e_ordine_dei_blocchi():
    righe = _righe(to_wp_html(_draft_completo()))
    for r in righe:
        assert r.startswith(("<p>", "<h2>", "<ul>")), r
        # un solo blocco per riga
        assert r.count("<p>") + r.count("<h2>") + r.count("<ul>") == 1, r
    tipi = [re.match(r"<(p|h2|ul)>", r).group(1) for r in righe]
    assert tipi == ["p", "p", "h2", "p", "h2", "p", "h2", "ul", "h2", "p"]


# --------------------------------------------------------------------------
# to_wp_html: escape
# --------------------------------------------------------------------------


def test_escape_di_e_commerciale_minore_maggiore():
    html = to_wp_html(_draft_con_paragrafi("Tom & Jerry, 2 < 3 e 3 > 2."))
    assert _p("Tom &amp; Jerry, 2 &lt; 3 e 3 &gt; 2.") in _righe(html)


def test_virgolette_tipografiche_restano_invariate():
    html = to_wp_html(_draft_con_paragrafi("Lui disse “ciao” e l’inizio è qui."))
    assert _p("Lui disse “ciao” e l’inizio è qui.") in _righe(html)
    assert "&#" not in html and "&rsquo;" not in html and "&ldquo;" not in html


def test_e_commerciale_nell_url_diventa_amp_dentro_href():
    html = to_wp_html(_draft_con_paragrafi("Vedi [la pagina](https://example.com/p?a=1&b=2) subito."))
    assert '<a href="https://example.com/p?a=1&amp;b=2">la pagina</a>' in html
    assert "a=1&b=2" not in html


def test_escape_nel_titolo_h2():
    draft = Draft(
        sections=[
            Section(kind="section", title="Tom & Jerry <3", paragraphs=["Testo."], items=[]),
        ]
    )
    assert "<h2><strong>Tom &amp; Jerry &lt;3</strong></h2>" in _righe(to_wp_html(draft))


def test_testo_con_script_esce_escapato_senza_tag_script():
    html = to_wp_html(_draft_con_paragrafi("Prova <script>alert(1)</script> fine."))
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script" not in html
    assert BeautifulSoup(html, "html.parser").find("script") is None


# --------------------------------------------------------------------------
# to_wp_html: struttura con BeautifulSoup
# --------------------------------------------------------------------------


def test_numero_di_h2_uguale_alle_sezioni_con_titolo():
    draft = _draft_completo()
    soup = BeautifulSoup(to_wp_html(draft), "html.parser")
    titolate = [s for s in draft.sections if s.title]
    assert len(titolate) == 4
    assert len(soup.find_all("h2")) == 4
    assert len(soup.find_all("ul")) == 1
    assert len(soup.find_all("li")) == 2


def test_nessun_tag_vietato_e_nessun_p_vuoto():
    soup = BeautifulSoup(to_wp_html(_draft_completo()), "html.parser")
    assert soup.find("script") is None
    assert soup.find("style") is None
    assert soup.find("iframe") is None
    for p in soup.find_all("p"):
        assert p.get_text().strip() != ""


def test_ogni_link_ha_href_https_e_nessun_rel_o_target():
    soup = BeautifulSoup(to_wp_html(_draft_completo()), "html.parser")
    links = soup.find_all("a")
    assert len(links) == 3
    for a in links:
        assert a.get("href", "").startswith("https")
        assert a.get("rel") is None and a.get("target") is None


def test_paragrafi_di_soli_spazi_non_producono_p_vuoti():
    html = to_wp_html(_draft_con_paragrafi("   ", "Testo vero.", "\t  "))
    soup = BeautifulSoup(html, "html.parser")
    testi = [p.get_text() for p in soup.find_all("p")]
    # intro + un solo paragrafo della sezione
    assert testi == ["Intro.", "Testo vero."]
    assert _p("") not in html


def test_intro_senza_titolo_non_produce_h2():
    draft = Draft(
        sections=[Section(kind="intro", title=None, paragraphs=["Solo intro."], items=[])]
    )
    html = to_wp_html(draft)
    assert "<h2" not in html
    assert _righe(html) == [_p("Solo intro.")]


# --------------------------------------------------------------------------
# build_cf_html
# --------------------------------------------------------------------------

FRAMMENTO = "<p><span style=\"font-weight: 400;\">Il film è l’inizio di “tutto”.</span></p>"


def _offsets(data: bytes) -> dict[str, str]:
    cifre = {}
    for nome in ("StartHTML", "EndHTML", "StartFragment", "EndFragment"):
        m = re.search(rb"(?m)^" + nome.encode() + rb":(\d+)", data)
        assert m is not None, f"manca {nome}"
        cifre[nome] = m.group(1).decode()
    return cifre


def test_cf_html_ritorna_bytes_con_versione():
    data = build_cf_html(FRAMMENTO)
    assert isinstance(data, bytes)
    assert data.startswith(b"Version:0.9")


def test_cf_html_offset_a_otto_cifre_con_zeri_a_sinistra():
    cifre = _offsets(build_cf_html(FRAMMENTO))
    for nome, valore in cifre.items():
        assert len(valore) == 8, f"{nome}={valore}"
        assert valore.isdigit()
    assert cifre["StartHTML"].startswith("0")


def test_cf_html_gli_offset_puntano_ai_marcatori():
    data = build_cf_html(FRAMMENTO)
    o = {k: int(v) for k, v in _offsets(data).items()}
    assert data[o["StartFragment"]:o["EndFragment"]].decode("utf-8") == FRAMMENTO
    html = data[o["StartHTML"]:o["EndHTML"]].decode("utf-8")
    assert html.startswith("<html>") and html.endswith("</html>")
    assert data[:o["StartFragment"]].endswith(b"<!--StartFragment-->")
    assert data[o["EndFragment"]:].startswith(b"<!--EndFragment-->")
    assert o["StartHTML"] < o["StartFragment"] < o["EndFragment"] < o["EndHTML"]


def test_cf_html_offset_in_byte_non_in_caratteri():
    data = build_cf_html(FRAMMENTO)
    o = {k: int(v) for k, v in _offsets(data).items()}
    lunghezza_byte = len(FRAMMENTO.encode("utf-8"))
    assert lunghezza_byte > len(FRAMMENTO)  # il frammento ha caratteri non ASCII
    assert o["EndFragment"] - o["StartFragment"] == lunghezza_byte
    # se gli offset fossero in caratteri, il frammento verrebbe tagliato male
    assert data[o["StartFragment"]:o["EndFragment"]].endswith("</p>".encode("utf-8"))


def test_cf_html_con_frammento_solo_ascii_ha_stessa_struttura():
    frammento = "<p>ciao</p>"
    data = build_cf_html(frammento)
    o = {k: int(v) for k, v in _offsets(data).items()}
    assert data[o["StartFragment"]:o["EndFragment"]] == frammento.encode("ascii")
    assert data[o["StartHTML"]:o["EndHTML"]].startswith(b"<html>")
