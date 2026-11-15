"""
tests/test_trend_publish_doc.py

Modello del testo del Trend Radar (nlp/trend_publish/doc.py): lettura del
testo incollato in sezioni, Markdown di lavoro e blocchi di testo semplice.
Contratto: nlp/trend_publish/README.md.
Non servono database ne' rete; il testo reale e' letto dal repo.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_trend_publish_doc.py
"""

import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nlp.trend_publish.doc import Draft, Section, markdown_to_draft, parse_draft  # noqa: E402

TESTO_REALE = ROOT / "output" / "trend_radar" / "20261109_20261113" / "00_input.md"


@pytest.fixture(scope="module")
def testo() -> str:
    return TESTO_REALE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def draft(testo) -> Draft:
    return parse_draft(testo)


# ---------------------------------------------------------------------------
# Testo reale
# ---------------------------------------------------------------------------

def test_testo_reale_sette_sezioni_nell_ordine(draft):
    assert [s.kind for s in draft.sections] == [
        "intro", "section", "section", "section", "section", "pdl", "sguardo",
    ]


def test_testo_reale_intro_senza_titolo_con_due_paragrafi(draft):
    intro = draft.sections[0]
    assert intro.title is None
    assert len(intro.paragraphs) == 2
    assert intro.paragraphs[0].startswith("Se mai vi foste persi nel rumore")
    assert intro.items == []


def test_testo_reale_titoli_delle_quattro_sezioni(draft):
    titoli = [s.title for s in draft.sections if s.kind == "section"]
    assert titoli == [
        "Black Doves, quando lo spy thriller si unisce al dramma famigliare",
        "Un cucciolo per Natale, il family perfetto per le feste",
        # nel file la riga ha uno spazio finale: il titolo e' senza
        "Godzilla Minus Zero, l’elaborazione collettiva di un lutto",
        "È tempo di ritornare nella Terra di Mezzo",
    ]


def test_testo_reale_numero_di_paragrafi_per_sezione(draft):
    sezioni = [s for s in draft.sections if s.kind == "section"]
    assert [len(s.paragraphs) for s in sezioni] == [4, 5, 6, 4]
    assert all(s.items == [] for s in sezioni)


def test_testo_reale_prima_di_lasciarci_titolo_canonico_e_cinque_item(draft):
    pdl = draft.sections[5]
    # nel file il titolo e' "Prima di lasciarci:" (con i due punti)
    assert pdl.title == "Prima di lasciarci"
    assert pdl.paragraphs == []
    assert len(pdl.items) == 5
    assert pdl.items[0] == "Look Back, la poesia di Kore-eda torna nelle sale."
    # l'ultimo item non ha punto finale e resta un item
    assert pdl.items[3] == "La Gradiva di Marine Atlan, un’incantevole sorpresa tra le rovine vesuviane"
    assert pdl.items[4].startswith("27ª edizione del Festival del Cinema Europeo di Lecce")


def test_testo_reale_sguardo_d_insieme(draft):
    sguardo = draft.sections[6]
    assert sguardo.title == "Uno sguardo d’insieme"
    assert len(sguardo.paragraphs) == 1
    assert sguardo.paragraphs[0].startswith("La settimana conferma")
    assert sguardo.items == []


def test_testo_reale_conserva_il_doppio_spazio_nel_paragrafo_di_godzilla(draft):
    godzilla = draft.sections[3]
    assert godzilla.title.startswith("Godzilla Minus Zero")
    assert any("Hiroshima e  Nagasaki" in p for p in godzilla.paragraphs)
    assert not any("Hiroshima e Nagasaki" in p for p in godzilla.paragraphs)


def test_testo_reale_nessun_paragrafo_con_spazi_agli_estremi(draft):
    for s in draft.sections:
        for blocco in s.paragraphs + s.items:
            assert blocco == blocco.strip()
            assert blocco != ""


def test_testo_reale_round_trip_markdown(draft):
    assert markdown_to_draft(draft.to_markdown()) == draft


def test_testo_reale_markdown_un_solo_a_capo_finale_e_nessuno_spazio_finale(draft):
    md = draft.to_markdown()
    assert md.endswith("\n")
    assert not md.endswith("\n\n")
    assert all(riga == riga.rstrip() for riga in md.split("\n"))


def test_testo_reale_titoli_markdown_con_due_cancelletti(draft):
    righe = draft.to_markdown().split("\n")
    for s in draft.sections:
        if s.kind == "intro":
            continue
        assert f"## {s.title}" in righe
    assert sum(1 for r in righe if r.startswith("## ")) == 6
    # l'intro non ha titolo: il testo inizia con il primo paragrafo
    assert righe[0] == draft.sections[0].paragraphs[0]


def test_testo_reale_plain_blocks_somma_di_paragrafi_e_item_senza_titoli(draft):
    blocchi = draft.plain_blocks()
    attesi = sum(len(s.paragraphs) + len(s.items) for s in draft.sections)
    assert len(blocchi) == attesi == 2 + 4 + 5 + 6 + 4 + 5 + 1
    titoli = {s.title for s in draft.sections if s.title}
    assert not (titoli & set(blocchi))
    # ordine: intro, poi sezioni, poi item, poi sguardo
    assert blocchi[0].startswith("Se mai vi foste persi")
    assert blocchi[-1].startswith("La settimana conferma")


# ---------------------------------------------------------------------------
# Casi piccoli
# ---------------------------------------------------------------------------

def test_riga_che_termina_con_punto_interrogativo_non_e_un_titolo():
    d = parse_draft("Com’è il Natale visto dagli amici a quattro zampe?\nUn testo che segue.")
    assert [s.kind for s in d.sections] == ["intro"]
    assert d.sections[0].paragraphs == [
        "Com’è il Natale visto dagli amici a quattro zampe?",
        "Un testo che segue.",
    ]


def test_riga_di_quindici_parole_senza_punto_non_e_un_titolo():
    quindici = "uno due tre quattro cinque sei sette otto nove dieci undici dodici tredici quattordici quindici"
    assert len(quindici.split()) == 15
    d = parse_draft(f"{quindici}\nTesto successivo.")
    assert [s.kind for s in d.sections] == ["intro"]
    assert d.sections[0].paragraphs == [quindici, "Testo successivo."]


def test_riga_di_quattordici_parole_senza_punto_e_un_titolo():
    quattordici = "uno due tre quattro cinque sei sette otto nove dieci undici dodici tredici quattordici"
    assert len(quattordici.split()) == 14
    d = parse_draft(f"Intro.\n{quattordici}\nTesto successivo.")
    assert [s.kind for s in d.sections] == ["intro", "section"]
    assert d.sections[1].title == quattordici
    assert d.sections[1].paragraphs == ["Testo successivo."]


def test_ultima_riga_senza_punto_non_seguita_da_altro_non_e_un_titolo():
    d = parse_draft("Intro.\nUna riga finale senza punto")
    assert [s.kind for s in d.sections] == ["intro"]
    assert d.sections[0].paragraphs == ["Intro.", "Una riga finale senza punto"]


@pytest.mark.parametrize("riga", ["Prima di lasciarci", "prima di lasciarci:", "PRIMA DI LASCIARCI:", "Prima di lasciarci:"])
def test_prima_di_lasciarci_riconosciuto_con_o_senza_due_punti_e_maiuscole(riga):
    d = parse_draft(f"Intro.\n\n{riga}\n\nPrimo item\nSecondo item senza punto\n")
    assert [s.kind for s in d.sections] == ["intro", "pdl"]
    assert d.sections[1].title == "Prima di lasciarci"
    assert d.sections[1].items == ["Primo item", "Secondo item senza punto"]
    assert d.sections[1].paragraphs == []


@pytest.mark.parametrize("riga", ["Uno sguardo d'insieme", "Uno sguardo d’insieme"])
def test_sguardo_d_insieme_riconosciuto_con_apostrofo_dritto_o_curvo(riga):
    d = parse_draft(f"Intro.\n\n{riga}\n\nLa settimana conferma tutto.\n")
    assert [s.kind for s in d.sections] == ["intro", "sguardo"]
    # il titolo si conserva come scritto (solo strip)
    assert d.sections[1].title == riga
    assert d.sections[1].paragraphs == ["La settimana conferma tutto."]


def test_sguardo_dopo_pdl_chiude_l_elenco_degli_item():
    testo = (
        "Intro.\n\nPrima di lasciarci:\nItem uno\nItem due senza punto\n\n"
        "Uno sguardo d’insieme\nUn paragrafo di chiusura.\n"
    )
    d = parse_draft(testo)
    assert [s.kind for s in d.sections] == ["intro", "pdl", "sguardo"]
    assert d.sections[1].items == ["Item uno", "Item due senza punto"]
    assert d.sections[2].paragraphs == ["Un paragrafo di chiusura."]


def test_testo_senza_titoli_e_solo_intro():
    d = parse_draft("Primo paragrafo.\n\nSecondo paragrafo.\nTerzo paragrafo.")
    assert [s.kind for s in d.sections] == ["intro"]
    assert d.sections[0].title is None
    assert d.sections[0].paragraphs == ["Primo paragrafo.", "Secondo paragrafo.", "Terzo paragrafo."]


def test_testo_vuoto_nessuna_sezione_o_solo_intro_vuota():
    # Il contratto dice "prima del primo titolo c'e' la sezione intro": con testo
    # vuoto sono lecite due letture, nessuna sezione oppure una sola intro senza
    # paragrafi. In entrambi i casi non ci sono blocchi di testo ne' titoli.
    for testo in ("", "   \n\n  \n"):
        d = parse_draft(testo)
        assert len(d.sections) <= 1
        for s in d.sections:
            assert s.kind == "intro"
            assert s.title is None
            assert s.paragraphs == []
            assert s.items == []
        assert d.plain_blocks() == []


def test_righe_vuote_ripetute_e_spazi_finali_vengono_ignorati():
    testo = "Intro con spazi finali.   \n\n\n\nTitolo della sezione  \n\n\nPrimo  paragrafo.  \n\n\nSecondo paragrafo.\n\n\n"
    d = parse_draft(testo)
    assert [s.kind for s in d.sections] == ["intro", "section"]
    assert d.sections[0].paragraphs == ["Intro con spazi finali."]
    assert d.sections[1].title == "Titolo della sezione"
    # il doppio spazio interno si conserva, lo strip agisce solo agli estremi
    assert d.sections[1].paragraphs == ["Primo  paragrafo.", "Secondo paragrafo."]


def test_titolo_che_non_e_il_primo_blocco_senza_intro_ha_intro_vuota_o_assente():
    # Testo che inizia direttamente con un titolo: l'intro, se presente, e' vuota.
    d = parse_draft("Un titolo qualunque\nUn paragrafo.\n")
    non_vuote = [s for s in d.sections if not (s.kind == "intro" and not s.paragraphs)]
    assert [s.kind for s in non_vuote] == ["section"]
    assert non_vuote[0].title == "Un titolo qualunque"
    assert non_vuote[0].paragraphs == ["Un paragrafo."]


def _draft_piccolo() -> Draft:
    return Draft(sections=[
        Section(kind="intro", title=None, paragraphs=["Prima riga.", "Seconda riga."], items=[]),
        Section(kind="section", title="Titolo", paragraphs=["P1.", "P2."], items=[]),
        Section(kind="pdl", title="Prima di lasciarci", paragraphs=[], items=["i1", "i2."]),
        Section(kind="sguardo", title="Uno sguardo d’insieme", paragraphs=["Fine."], items=[]),
    ])


def test_to_markdown_forma_esatta():
    atteso = (
        "Prima riga.\n\nSeconda riga.\n\n"
        "## Titolo\n\nP1.\n\nP2.\n\n"
        "## Prima di lasciarci\n\n- i1\n- i2.\n\n"
        "## Uno sguardo d’insieme\n\nFine.\n"
    )
    assert _draft_piccolo().to_markdown() == atteso


def test_round_trip_di_un_draft_costruito_a_mano():
    d = _draft_piccolo()
    assert markdown_to_draft(d.to_markdown()) == d


def test_markdown_to_draft_legge_intro_titoli_e_item():
    md = "Intro uno.\n\nIntro due.\n\n## Una sezione\n\nTesto.\n\n## Prima di lasciarci\n\n- a\n- b\n"
    d = markdown_to_draft(md)
    assert [s.kind for s in d.sections] == ["intro", "section", "pdl"]
    assert d.sections[0].paragraphs == ["Intro uno.", "Intro due."]
    assert d.sections[1].title == "Una sezione"
    assert d.sections[1].paragraphs == ["Testo."]
    assert d.sections[2].items == ["a", "b"]


def test_plain_blocks_del_draft_piccolo():
    assert _draft_piccolo().plain_blocks() == [
        "Prima riga.", "Seconda riga.", "P1.", "P2.", "i1", "i2.", "Fine.",
    ]
