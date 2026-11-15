"""
tests/test_trend_publish_pipeline.py

Integrazione del flusso nlp/trend_publish con dati inline, senza rete e senza
database: parse_draft -> correzioni -> link interni -> corsivo sui titoli ->
link esterni -> to_markdown -> to_wp_html.

Modo scelto per le correzioni: validate_edits e apply_edits lavorano sul testo
intero incollato (per verificare "solo le modifiche elencate"); poi l'helper
_correggi_draft applica gli edit accettati al testo di ogni paragrafo/item del
Draft gia' letto con parse_draft (titoli esclusi).

Esecuzione (dalla root del repo):
    python -m pytest tests/test_trend_publish_pipeline.py
"""

import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup  # noqa: E402

from nlp.trend_publish.doc import Draft, Section, parse_draft  # noqa: E402
from nlp.trend_publish.external_links import UrlCheck, pick_external, verify_url  # noqa: E402
from nlp.trend_publish.grammar import Edit, apply_edits, only_listed_changes, validate_edits  # noqa: E402
from nlp.trend_publish.linker import (  # noqa: E402
    LinkSpec,
    apply_external_links,
    apply_internal_links,
    italicize_titles,
)
from nlp.trend_publish.wp_html import to_wp_html  # noqa: E402

URL_BD = "https://www.taxidrivers.it/564645/serie-tv/black-doves-2.html"
URL_LB = "https://www.taxidrivers.it/551853/review/look-back.html"
URL_EXT = "https://www.labiennale.org/it/cinema/2026"

TESTO = """Questa settimana il pubblico cerca storie di legami e di perdite.

Black Doves, quando lo spy thriller si unisce al dramma famigliare
Black Doves è tornata e ha aiutato a un intero paese a elaborare il passato, tra spie e segreti di famiglia.
Il pubblico si affeziona ai personaggi, e la seconda stagione di Black Doves lo conferma.

Prima di lasciarci:
Recuperiamo Look Back di Fujimoto
Aspettiamo Black Doves 2

Uno sguardo d’insieme
La settimana racconta un pubblico che cerca emozioni.
"""

TITOLO_SEZIONE = "Black Doves, quando lo spy thriller si unisce al dramma famigliare"
ORIGINALE = "ha aiutato a un intero paese"
CORRETTO = "ha aiutato un intero paese"

EDITS = [Edit(id="e1", original=ORIGINALE, replacement=CORRETTO, category="preposizione", reason="a di troppo")]


def _correggi_draft(draft: Draft, accepted) -> Draft:
    """Applica gli edit accettati a ogni paragrafo e item (mai ai titoli)."""

    def fix(testo: str) -> str:
        pertinenti = [e for e in accepted if e.original in testo]
        return apply_edits(testo, pertinenti) if pertinenti else testo

    return Draft(
        sections=[
            Section(
                kind=s.kind,
                title=s.title,
                paragraphs=[fix(p) for p in s.paragraphs],
                items=[fix(i) for i in s.items],
            )
            for s in draft.sections
        ]
    )


def _senza_markup(md: str) -> str:
    md = re.sub(r"\[\*\*\*(.+?)\*\*\*\]\([^)]*\)", r"\1", md)
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)
    md = re.sub(r"\*([^*\n]+)\*", r"\1", md)
    return md


def _http_finta(url):
    return 200, url, "<html>La Biennale Cinema 2026 presenta il programma.</html>"


def _esegui(testo: str) -> dict:
    draft = parse_draft(testo)

    accepted, rejected = validate_edits(testo, EDITS)
    corretto_testo = apply_edits(testo, accepted)
    draft = _correggi_draft(draft, accepted)

    draft, rapporto_interni = apply_internal_links(
        draft,
        [
            LinkSpec(surface="Black Doves", url=URL_BD, scope="body"),
            LinkSpec(surface="Look Back", url=URL_LB, scope="pdl"),
        ],
    )
    draft = italicize_titles(draft, ["Black Doves", "Look Back"])

    check = verify_url(URL_EXT, "Biennale", _http_finta)
    picks, satisfied = pick_external(
        [{"url": URL_EXT, "anchor": "spie e segreti di famiglia", "authority": 80, "check": check}],
        min_links=1,
    )
    draft, rapporto_esterni = apply_external_links(
        draft, [{"anchor": p["anchor"], "url": p["url"]} for p in picks]
    )

    md = draft.to_markdown()
    return {
        "accepted": accepted,
        "rejected": rejected,
        "corretto_testo": corretto_testo,
        "interni": rapporto_interni,
        "esterni": rapporto_esterni,
        "satisfied": satisfied,
        "md": md,
        "html": to_wp_html(draft),
    }


# --------------------------------------------------------------------------


def test_la_correzione_e_accettata_e_solo_quella():
    r = _esegui(TESTO)
    assert [e.id for e in r["accepted"]] == ["e1"]
    assert r["rejected"] == []
    assert only_listed_changes(TESTO, r["corretto_testo"], r["accepted"]) is True
    assert CORRETTO in r["corretto_testo"]
    assert "a un intero paese" not in r["corretto_testo"]


def test_testo_finale_contiene_la_correzione_e_non_l_errore():
    r = _esegui(TESTO)
    assert CORRETTO in r["md"]
    assert ORIGINALE not in r["md"]


def test_rimosso_il_markup_il_testo_e_quello_corretto_senza_altre_differenze():
    r = _esegui(TESTO)
    atteso = parse_draft(r["corretto_testo"]).to_markdown()
    assert _senza_markup(r["md"]) == atteso


def test_link_interni_applicati_con_posizione():
    r = _esegui(TESTO)
    assert [v["applied"] for v in r["interni"]] == [True, True]
    assert r["interni"][0]["where"] == "1/0"  # prima occorrenza nel corpo
    assert r["interni"][1]["where"] == "2/0"  # prima voce del pdl
    assert f"[***Black Doves***]({URL_BD})" in r["md"]
    assert f"[***Look Back***]({URL_LB})" in r["md"]
    assert r["md"].count(f"]({URL_BD})") == 1  # solo la prima citazione


def test_link_esterno_applicato_una_sola_volta_senza_attributi():
    r = _esegui(TESTO)
    assert r["satisfied"] is True
    assert [v["applied"] for v in r["esterni"]] == [True]
    assert r["md"].count(f"[spie e segreti di famiglia]({URL_EXT})") == 1


def test_titoli_d_opera_in_corsivo_anche_nel_titolo_di_sezione():
    r = _esegui(TESTO)
    assert f"## *Black Doves*, quando lo spy thriller si unisce al dramma famigliare" in r["md"]
    assert "*Black Doves*" in r["md"]
    assert "<em>Black Doves</em>, quando lo spy thriller" in r["html"]


def test_html_tre_h2_e_un_ul():
    soup = BeautifulSoup(_esegui(TESTO)["html"], "html.parser")
    assert len(soup.find_all("h2")) == 3  # sezione, prima di lasciarci, sguardo
    assert len(soup.find_all("ul")) == 1
    assert len(soup.find_all("li")) == 2
    assert [h.get_text() for h in soup.find_all("h2")] == [
        TITOLO_SEZIONE,
        "Prima di lasciarci",
        "Uno sguardo d’insieme",
    ]


def test_html_tutti_i_link_https_e_ben_formato():
    html = _esegui(TESTO)["html"]
    soup = BeautifulSoup(html, "html.parser")  # non deve sollevare
    links = soup.find_all("a")
    assert len(links) == 3
    for a in links:
        assert a.get("href", "").startswith("https")
    assert html.count("<p>") == html.count("</p>")
    assert html.count("<h2>") == html.count("</h2>")
    assert html.count("<ul>") == html.count("</ul>") == 1
    assert soup.find("script") is None


def test_html_senza_i_due_punti_di_prima_di_lasciarci():
    html = _esegui(TESTO)["html"]
    assert "Prima di lasciarci:" not in html
    assert "<h2><strong>Prima di lasciarci</strong></h2>" in html


def test_html_contiene_correzione_e_paragrafi_nel_formato_del_sito():
    html = _esegui(TESTO)["html"]
    assert CORRETTO in html
    assert '<p><span style="font-weight: 400;">Questa settimana il pubblico cerca' in html
    assert f'<a href="{URL_BD}"><em><strong>Black Doves</strong></em></a>' in html


def test_seconda_esecuzione_produce_lo_stesso_html():
    a = _esegui(TESTO)
    b = _esegui(TESTO)
    assert a["html"] == b["html"]
    assert a["md"] == b["md"]
