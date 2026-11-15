"""
tests/test_style_profile.py

Profilo di stile del Trend Radar (nlp/style_profile): lettura degli articoli
in sezioni, metriche senza modello linguistico, divieti e stilometria.
Non servono database ne' rete; il test su spaCy si salta se il modello non
e' installato.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_style_profile.py
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nlp.style_profile.metrics import _verdict, count_italics, find_divieti, mattr  # noqa: E402
from nlp.style_profile.parsing import (  # noqa: E402
    classify_heading,
    heading_italics_only,
    sections_from_html,
    sections_from_markdown,
    strip_md,
)
from nlp.style_profile.stylometry import cosine_delta, strip_formula, tokenize  # noqa: E402
from nlp.style_profile import titles as T  # noqa: E402

HTML = """
<p>Se mai vi foste persi nel rumore, ecco una panoramica dei trend di <strong>TaxiDrivers</strong>.</p>
<p>Una serie <em>Apple </em>ci porta lontano.</p>
<script>alert('x')</script>
<h2><strong><em>Lupin</em>, il ritorno</strong></h2>
<p>Testo del corpo con <a href="https://www.taxidrivers.it/1/x.html"><em>Lupin</em></a> e
<a href="https://spam.example.com/">un link esterno</a>.</p>
<p class="wp-caption-text">Foto: didascalia</p>
<h2> </h2>
<p>Seguito della stessa sezione.</p>
<h2><strong>Prima di lasciarci:</strong></h2>
<ul><li>Prepariamoci al <a href="https://www.taxidrivers.it/2/dune.html">ritorno di <em>Dune</em></a>.</li></ul>
<h2>Uno sguardo d’insieme</h2>
<p>La settimana conferma che il pubblico cerca altro.</p>
"""


def test_html_sections_types_and_order():
    secs = sections_from_html(HTML)
    assert [s.section_type for s in secs] == ["intro", "corpo", "prima_di_lasciarci", "sguardo"]
    assert secs[1].heading == "Lupin, il ritorno"
    assert secs[2].items == ["Prepariamoci al ritorno di Dune."]


def test_html_drops_scripts_captions_and_external_links():
    secs = sections_from_html(HTML)
    full = "\n".join(s.text_md for s in secs)
    assert "alert" not in full
    assert "didascalia" not in full
    assert "spam.example.com" not in full and "un link esterno" in full
    assert "[*Lupin*](https://www.taxidrivers.it/1/x.html)" in full


def test_empty_heading_does_not_split_section():
    corpo = [s for s in sections_from_html(HTML) if s.section_type == "corpo"]
    assert len(corpo) == 1
    assert "Seguito della stessa sezione." in corpo[0].text_plain


def test_italic_markers_keep_spaces_outside():
    intro = sections_from_html(HTML)[0]
    assert "*Apple* ci porta" in intro.text_md


def test_markdown_sections():
    md = "# Titolo\n\n## Intro\n\nPrimo.\n\nSecondo.\n\n## Prima di lasciarci\n\n- Voce uno.\n- Voce due.\n\n## Uno sguardo d'insieme\n\nChiusa."
    secs = sections_from_markdown(md)
    assert [s.section_type for s in secs] == ["intro", "prima_di_lasciarci", "sguardo"]
    assert secs[0].paragraphs == ["Primo.", "Secondo."]
    assert secs[1].items == ["Voce uno.", "Voce due."]


@pytest.mark.parametrize("heading,expected", [
    (None, "intro"),
    ("Prima di lasciarci", "prima_di_lasciarci"),
    ("Uno sguardo d’insieme", "sguardo"),
    ("Gli spunti della settimana", "spunti"),
    ("Dio ride, il coraggio di essere eretici", "corpo"),
])
def test_classify_heading(heading, expected):
    assert classify_heading(heading) == expected


def test_strip_md_and_italics():
    md = "[***Lupin***](https://x) e *Dune*, ma **Netflix** no."
    assert strip_md(md) == "Lupin e Dune, ma Netflix no."
    assert count_italics(md) == 2


def test_mattr():
    assert mattr(["a", "b", "c", "d"]) == 1.0
    assert mattr(["a"] * 100) == pytest.approx(1 / 50)


def test_verdict_uses_min_max_with_few_sections():
    stats = {"min": 1, "p10": 2, "mediana": 3, "p90": 4, "max": 5}
    assert _verdict(3, stats, n_docs=10) == "ok"
    assert _verdict(1.5, stats, n_docs=10) == "ai margini"
    assert _verdict(1.5, stats, n_docs=4) == "ok"
    assert _verdict(6, stats, n_docs=10) == "sopra"


def test_find_divieti():
    divieti = [{"pattern": r"\bin conclusione\b", "motivo": "annuncio"}]
    hits = find_divieti("In conclusione, bene.", divieti)
    assert hits[0]["trovato"] == "In conclusione" and hits[0]["livello"] == "vietato"


def test_formula_is_removed_from_stylometry():
    text = ("Se mai vi foste persi nel rumore, ecco una panoramica dei trend più apprezzati dal pubblico "
            "di TaxiDrivers nella settimana dal 2 al 6 novembre. Netflix punta sul thriller.")
    assert strip_formula(text).strip() == "Netflix punta sul thriller."
    assert "rumore" not in tokenize(text)


def test_cosine_delta():
    assert cosine_delta([1, 0], [1, 0]) == pytest.approx(0.0)
    assert cosine_delta([1, 0], [-1, 0]) == pytest.approx(2.0)


def test_slug_echo_counts_words_in_a_row_with_the_url_slug():
    from nlp.style_profile.metrics import slug_echo, slug_tokens

    url = "https://www.taxidrivers.it/563124/live-streaming-on-demand/prime-video-film/drive-the-pretenders-quando-lamore-corre-senza-freni.html"
    assert slug_tokens(url)[:3] == ["drive", "the", "pretenders"]
    echo = f"[*Drive*]({url}), la nuova serie Prime che mette d'accordo motori e sentimenti."
    assert slug_echo(echo) == 0  # "Drive" e' in corsivo: e' il titolo, non conta
    copy = f"Su Prime Video *Drive the Pretenders*, [quando l'amore corre senza freni]({url})."
    assert slug_echo(copy) == 5  # "quando l'amore corre senza freni"; il titolo in corsivo non conta
    title_only = f"[*Drive the Pretenders*]({url}), la nuova serie Prime."
    assert slug_echo(title_only) == 0
    assert slug_echo("Una voce senza link.") == 0


# ---------------------------------------------------------------------------
# Titoli delle sezioni
# ---------------------------------------------------------------------------

def test_heading_italics_only_moves_punctuation_out_and_drops_bold_and_links():
    assert heading_italics_only("***Habeas Corpus* è il primo legal drama**") == "*Habeas Corpus* è il primo legal drama"
    assert heading_italics_only("*Sterling Point,* crescere è un mistero") == "*Sterling Point*, crescere è un mistero"
    assert heading_italics_only("[***El Mazaròl***](https://www.taxidrivers.it/1/x.html), la leggenda") == "*El Mazaròl*, la leggenda"
    assert heading_italics_only("Prima di lasciarci:") == "Prima di lasciarci"


def test_html_heading_md_keeps_italics_only():
    html = '<h2><strong><em>Fatherland</em>, lungo la strada della memoria</strong></h2><p>Testo.</p>'
    s = sections_from_html(html)[0]
    assert s.heading == "Fatherland, lungo la strada della memoria"
    assert s.heading_md == "*Fatherland*, lungo la strada della memoria"


def test_markdown_heading_keeps_italics():
    secs = sections_from_markdown("## *Balcanica*, riprendersi la propria musica\n\nTesto.")
    assert secs[0].heading_md == "*Balcanica*, riprendersi la propria musica"
    assert secs[0].heading == "Balcanica, riprendersi la propria musica"


def test_extract_titles_block():
    text = ("## Titoli delle sezioni\n1. *Fatherland*, lungo la strada della memoria\n- Tornano i furti di Lupin su Netflix\n\n"
            "## Intro\n\nTesto.\n")
    entries, rest = T.extract_titles_block(text)
    assert [e["heading_md"] for e in entries] == ["*Fatherland*, lungo la strada della memoria", "Tornano i furti di Lupin su Netflix"]
    assert [e["heading"] for e in entries][0] == "Fatherland, lungo la strada della memoria"
    assert "Titoli delle sezioni" not in rest and "## Intro" in rest
    assert T.extract_titles_block("## Intro\n\nTesto.")[0] is None


def test_first_separator_ignores_quotes_and_parentheses():
    assert T.first_separator("Serpenti, e la violenza") == (8, ",")
    assert T.first_separator("Dead “lavoro, al miele” dolce") == (-1, "")
    assert T.first_separator("Se (domani, forse) non torno: rinascere") == (28, ":")


def test_normalize_title_fixes_space_after_apostrophe():
    assert T.normalize_title("L’ horror “prestige”") == "L’horror “prestige”"


def test_naive_bayes_prefers_the_class_with_the_trait():
    def f(**kw):
        base = {"parole": 7, "lettura_parole": 4, "struttura": "frase", "ancora_tipo": "nome", "lettura_tipo": "assente",
                "finale": "nessuno", "ha_tra": 0, "inizia_articolo": 0, "ha_verbo_finito": 0, "virgolette": 0,
                "parentesi": 0, "due_punti": 0, "maiuscole_interne": 0, "ancora_in_corsivo": 0}
        base.update(kw)
        return base

    author = [f(struttura="ancora_lettura") for _ in range(10)]
    others = [f(struttura="sintagma") for _ in range(10)]
    model = T.NaiveBayes(author, others)
    assert model.score(f(struttura="ancora_lettura")) > 0 > model.score(f(struttura="sintagma"))
    # leave-one-out: il punteggio di un elemento dell'autore non conta se stesso
    assert model.score(author[0], "a") < model.score(author[0])


def test_auc():
    assert T.auc([3, 4], [1, 2]) == 1.0
    assert T.auc([1, 2], [1, 2]) == 0.5


def test_analyze_titles_structures_with_spacy():
    spacy = pytest.importorskip("spacy")
    try:
        spacy.load("it_core_news_lg")
    except OSError:
        pytest.skip("modello it_core_news_lg non installato")
    azione = T.analyze_titles([
        {"heading": "Wild Horse Nine porta il golpe sull'Isola di Pasqua", "heading_md": "*Wild Horse Nine* porta il golpe sull'Isola di Pasqua"},
        {"heading": "Rider è qualcosa di unico", "heading_md": "*Rider* è qualcosa di unico"},
    ])
    assert azione[0]["opera_verbo_azione"] == 1 and azione[1]["opera_verbo_azione"] == 0
    items = [
        {"heading": "Fatherland, lungo la strada della memoria", "heading_md": "*Fatherland*, lungo la strada della memoria"},
        {"heading": "Tornano i furti di Lupin su Netflix"},
        {"heading": "Gli Emmy Awards premiano gli streamers"},
        {"heading": "Alcune proposte per settembre"},
        {"heading": "Have a seat", "heading_md": "*Have a seat*"},
        {"heading": "Dead-End Job: Un Thriller Distopico Che Fa Riflettere"},
    ]
    f = T.analyze_titles(items)
    assert [x["struttura"] for x in f] == ["ancora_lettura", "frase", "frase", "sintagma", "solo_titolo", "ancora_lettura"]
    assert f[0]["ancora_tipo"] == "nome" and f[0]["lettura_tipo"] == "preposizione" and f[0]["ancora_in_corsivo"] == 1
    assert f[2]["ancora"] == "Gli Emmy Awards" and f[2]["ancora_tipo"] == "evento"
    assert f[5]["separatore"] == ":" and f[5]["maiuscole_interne"] >= 3


def test_features_with_spacy():
    spacy = pytest.importorskip("spacy")
    try:
        spacy.load("it_core_news_lg")
    except OSError:
        pytest.skip("modello it_core_news_lg non installato")
    from nlp.style_profile.metrics import features

    f = features("La settimana conferma il ritorno del genere. Infine, Netflix ci mostra un nuovo thriller.")
    assert f["frasi"] == 2
    assert f["quota_attacco_connettivo"] == pytest.approx(0.5)
    assert f["prima_plurale_x1000"] > 0
