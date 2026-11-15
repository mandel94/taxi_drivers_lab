"""
tests/test_trend_publish_grammar.py

Fase 1 di nlp/trend_publish: correzione grammaticale del testo del Trend Radar
(nlp/trend_publish/grammar.py). Si testano solo le regole del contratto
(README.md): il giudizio semantico (cosa e' un errore) non e' verificabile dal
codice e spetta ai sottoagenti della skill.
Non servono database ne' rete.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_trend_publish_grammar.py
"""

import copy
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nlp.trend_publish.grammar import (  # noqa: E402
    ALLOWED_CATEGORIES,
    Edit,
    Rejection,
    apply_edits,
    only_listed_changes,
    render_report,
    validate_edits,
)


def E(id, original, replacement, category, reason="correzione di prova"):
    return Edit(id=id, original=original, replacement=replacement, category=category, reason=reason)


# --------------------------------------------------------------------------
# Categorie ammesse
# --------------------------------------------------------------------------

def test_categorie_ammesse_sono_quelle_del_contratto():
    assert ALLOWED_CATEGORIES == frozenset({
        "ortografia", "accento", "apostrofo", "doppie", "concordanza",
        "tempo_verbale", "congiuntivo", "preposizione", "articolo", "refuso",
    })
    assert "spazi" not in ALLOWED_CATEGORIES
    assert "stile" not in ALLOWED_CATEGORIES


# --------------------------------------------------------------------------
# validate_edits: edit validi (casi reali)
# --------------------------------------------------------------------------

CASI_VALIDI = [
    pytest.param(
        "Il film ha aiutato a un intero paese a elaborare il lutto.",
        "ha aiutato a un intero paese a elaborare",
        "ha aiutato un intero paese a elaborare",
        "preposizione",
        id="preposizione",
    ),
    pytest.param(
        "Il regista osserva la citta' da un alto, poi si ferma.",
        "da un alto",
        "da un lato",
        "refuso",
        id="refuso",
    ),
    pytest.param(
        "Non sappiamo perche il film sia stato dimenticato.",
        "perche",
        "perché",
        "accento",
        id="accento",
    ),
    pytest.param(
        "Ha incontrato un'amico di lunga data.",
        "un'amico",
        "un amico",
        "apostrofo",
        id="apostrofo",
    ),
    pytest.param(
        "Il documentario mostra che le ferite sono ancora vivo nella memoria.",
        "le ferite sono ancora vivo",
        "le ferite sono ancora vive",
        "concordanza",
        id="concordanza",
    ),
]


@pytest.mark.parametrize("text, original, replacement, category", CASI_VALIDI)
def test_edit_valido_e_accettato_e_applicato(text, original, replacement, category):
    edit = E("1", original, replacement, category)
    accepted, rejected = validate_edits(text, [edit])
    assert accepted == [edit]
    assert rejected == []
    assert apply_edits(text, accepted) == text.replace(original, replacement)


def test_edit_valido_con_zona_protetta_altrove_e_accettato():
    text = "Godzilla Minus Zero ha vinto, ma non sappiamo perche."
    edit = E("1", "perche", "perché", "accento")
    accepted, rejected = validate_edits(text, [edit], protected=("Godzilla Minus Zero",))
    assert accepted == [edit]
    assert rejected == []


# --------------------------------------------------------------------------
# validate_edits: ogni motivo di rifiuto
# --------------------------------------------------------------------------

def _solo_rifiuto(text, edit, protected=()):
    accepted, rejected = validate_edits(text, [edit], protected=protected)
    assert accepted == []
    assert len(rejected) == 1
    assert isinstance(rejected[0], Rejection)
    assert rejected[0].edit == edit
    return rejected[0].reason


def test_rifiuta_categoria_non_ammessa():
    text = "L'incantevole film arriva nelle sale."
    edit = E("1", "incantevole", "bella", "stile")
    assert _solo_rifiuto(text, edit) == "categoria non ammessa"


def test_rifiuta_spazi_doppi_come_categoria_non_ammessa():
    text = "Il racconto unisce Hiroshima e  Nagasaki in un solo dolore."
    edit = E("1", "Hiroshima e  Nagasaki", "Hiroshima e Nagasaki", "spazi")
    assert _solo_rifiuto(text, edit) == "categoria non ammessa"


def test_rifiuta_frammento_assente():
    text = "Il film arriva nelle sale a dicembre."
    edit = E("1", "perche", "perché", "accento")
    assert _solo_rifiuto(text, edit) == "frammento assente"


def test_rifiuta_frammento_vuoto_come_assente():
    text = "Il film arriva nelle sale a dicembre."
    edit = E("1", "", "perché", "accento")
    assert _solo_rifiuto(text, edit) == "frammento assente"


def test_rifiuta_frammento_ambiguo_se_compare_due_volte():
    text = "Il gatto dorme e il gatto sogna."
    edit = E("1", "gatto", "gato", "ortografia")
    assert _solo_rifiuto(text, edit) == "frammento ambiguo"


def test_rifiuta_nessuna_modifica():
    text = "Non sappiamo perche il film sia stato dimenticato."
    edit = E("1", "perche", "perche", "accento")
    assert _solo_rifiuto(text, edit) == "nessuna modifica"


def test_rifiuta_modifica_in_stringa_protetta():
    text = "Il film Godzilla Minus Zero arriva nelle sale."
    edit = E("1", "Minus Zero", "Minus Zer0", "refuso")
    reason = _solo_rifiuto(text, edit, protected=("Godzilla Minus Zero",))
    assert reason == "tocca una zona protetta"


def test_rifiuta_modifica_dentro_link_markdown():
    text = "Leggi [Titolo](https://www.taxidrivers.it/1/a.html) per sapere di piu'."
    edit = E("1", "Titolo", "Titoli", "refuso")
    assert _solo_rifiuto(text, edit) == "tocca una zona protetta"


def test_rifiuta_modifica_dentro_url():
    text = "Il comunicato e' su https://www.taxidrivers.it/2/b.html da stamattina."
    edit = E("1", "taxidrivers", "taxidrivar", "refuso")
    assert _solo_rifiuto(text, edit) == "tocca una zona protetta"


def test_rifiuta_modifica_troppo_estesa():
    text = "In sala il film racconta una storia semplice davvero."
    edit = E("1", "il film racconta una storia semplice",
             "la serie mostra un racconto complesso", "refuso")
    assert _solo_rifiuto(text, edit) == "modifica troppo estesa"


def test_rifiuta_modifica_sovrapposta_a_una_gia_accettata():
    text = "Il film e' stato visto da molti spettatori ieri."
    e1 = E("1", "visto da molti", "visto da tanti", "ortografia")
    e2 = E("2", "da molti spettatori", "da molti spettatrici", "concordanza")
    accepted, rejected = validate_edits(text, [e1, e2])
    assert accepted == [e1]
    assert [r.edit for r in rejected] == [e2]
    assert rejected[0].reason == "sovrapposto a un'altra modifica"


def test_lotto_misto_conserva_ordine_di_input_degli_accettati():
    text = "Non sappiamo perche il film arrivi. Ha un'amico e le ferite sono ancora vivo."
    e_ok_tardi = E("a", "le ferite sono ancora vivo", "le ferite sono ancora vive", "concordanza")
    e_ko = E("b", "incantevole", "bella", "stile")
    e_ok_presto = E("c", "perche", "perché", "accento")
    e_ok_medio = E("d", "un'amico", "un amico", "apostrofo")
    accepted, rejected = validate_edits(text, [e_ok_tardi, e_ko, e_ok_presto, e_ok_medio])
    # ordine di input, non ordine di posizione nel testo
    assert [e.id for e in accepted] == ["a", "c", "d"]
    assert [r.edit.id for r in rejected] == ["b"]
    assert rejected[0].reason == "categoria non ammessa"


# --------------------------------------------------------------------------
# apply_edits
# --------------------------------------------------------------------------

TESTO_DUE_PARAGRAFI = (
    "Primo paragrafo con un'amico e perche no.\n\n"
    "Secondo paragrafo: le ferite sono ancora vivo, e il resto resta  uguale."
)
EDIT_DUE_PARAGRAFI = [
    E("1", "un'amico", "un amico", "apostrofo"),
    E("2", "perche", "perché", "accento"),
    E("3", "ancora vivo", "ancora vive", "concordanza"),
]
TESTO_DUE_PARAGRAFI_CORRETTO = (
    "Primo paragrafo con un amico e perché no.\n\n"
    "Secondo paragrafo: le ferite sono ancora vive, e il resto resta  uguale."
)


def test_apply_edits_applica_piu_modifiche_anche_nello_stesso_paragrafo():
    out = apply_edits(TESTO_DUE_PARAGRAFI, EDIT_DUE_PARAGRAFI)
    assert out == TESTO_DUE_PARAGRAFI_CORRETTO


def test_apply_edits_ordine_inverso_non_altera_il_risultato():
    out = apply_edits(TESTO_DUE_PARAGRAFI, list(reversed(EDIT_DUE_PARAGRAFI)))
    assert out == TESTO_DUE_PARAGRAFI_CORRETTO


def test_apply_edits_con_lista_vuota_ritorna_il_testo_uguale():
    assert apply_edits(TESTO_DUE_PARAGRAFI, []) == TESTO_DUE_PARAGRAFI


# --------------------------------------------------------------------------
# only_listed_changes
# --------------------------------------------------------------------------

def test_only_listed_changes_true_se_corretto_e_apply_edits():
    corrected = apply_edits(TESTO_DUE_PARAGRAFI, EDIT_DUE_PARAGRAFI)
    assert only_listed_changes(TESTO_DUE_PARAGRAFI, corrected, EDIT_DUE_PARAGRAFI) is True


def test_only_listed_changes_false_con_modifica_in_piu():
    corrected = apply_edits(TESTO_DUE_PARAGRAFI, EDIT_DUE_PARAGRAFI)
    # cambio non elencato: il punto finale diventa un punto esclamativo
    assert corrected.endswith("uguale.")
    corrected = corrected[:-1] + "!"
    assert only_listed_changes(TESTO_DUE_PARAGRAFI, corrected, EDIT_DUE_PARAGRAFI) is False


def test_only_listed_changes_false_se_manca_una_modifica_e_c_e_una_differenza_non_coperta():
    # applico solo la prima modifica, e in piu' cambio una parola non elencata
    parziale = apply_edits(TESTO_DUE_PARAGRAFI, EDIT_DUE_PARAGRAFI[:1])
    parziale = parziale.replace("Secondo paragrafo", "Terzo paragrafo")
    assert only_listed_changes(TESTO_DUE_PARAGRAFI, parziale, EDIT_DUE_PARAGRAFI) is False


def test_only_listed_changes_false_con_lista_vuota_e_testo_cambiato():
    assert only_listed_changes("Ciao mondo.", "Ciao mondo!", []) is False


def test_only_listed_changes_true_con_liste_vuote_e_testo_identico():
    assert only_listed_changes("Ciao mondo.", "Ciao mondo.", []) is True


# --------------------------------------------------------------------------
# Testo pulito
# --------------------------------------------------------------------------

def test_testo_pulito_nessuna_correzione_necessaria():
    pulito = "Una settimana tranquilla.\n\nIl pubblico cerca altro, e lo trova."
    accepted, rejected = validate_edits(pulito, [])
    assert accepted == []
    assert rejected == []
    out = apply_edits(pulito, accepted)
    assert out == pulito
    assert only_listed_changes(pulito, out, accepted) is True
    assert "Nessuna correzione necessaria." in render_report(accepted, rejected, [])


# --------------------------------------------------------------------------
# render_report
# --------------------------------------------------------------------------

DUBBIO = {
    "fragment": "in una sala adibita di godere un’immagine quasi quadrata",
    "note": "frase malformata: non e' una correzione univoca",
}


def _report_completo():
    accepted = [
        E("1", "ha aiutato a un intero paese", "ha aiutato un intero paese",
          "preposizione", "il verbo e' transitivo"),
        E("2", "perche", "perché", "accento", "manca la vocale tonica"),
    ]
    rejected = [
        Rejection(edit=E("3", "incantevole", "bella", "stile", "piu' semplice"),
                  reason="categoria non ammessa"),
    ]
    return accepted, rejected, [DUBBIO]


def test_render_report_titolo_e_riepilogo():
    report = render_report(*_report_completo())
    assert report.splitlines()[0].strip() == "# Correzioni grammaticali"
    assert "2 correzioni applicate, 1 rifiutate, 1 dubbi non toccati" in report


def test_render_report_tabella_con_prima_dopo_categoria_motivo():
    report = render_report(*_report_completo())
    prima_dei_rifiuti = report.split("## Rifiutate")[0]
    righe_tabella = [r for r in prima_dei_rifiuti.splitlines() if r.lstrip().startswith("|")]
    intestazione = righe_tabella[0].casefold()
    for colonna in ("prima", "dopo", "categoria", "motivo"):
        assert colonna in intestazione
    tabella = "\n".join(righe_tabella)
    for frammento in ("ha aiutato a un intero paese", "ha aiutato un intero paese", "perche",
                      "perché", "preposizione", "accento", "il verbo e' transitivo",
                      "manca la vocale tonica"):
        assert frammento in tabella


def test_render_report_conteggio_per_categoria():
    accepted = [
        E("1", "perche", "perché", "accento", "motivo uno"),
        E("2", "piu", "più", "accento", "motivo due"),
        E("3", "un'amico", "un amico", "apostrofo", "motivo tre"),
    ]
    report = render_report(accepted, [], [])
    assert "3 correzioni applicate, 0 rifiutate, 0 dubbi non toccati" in report
    fuori_tabella = [r for r in report.splitlines() if not r.lstrip().startswith("|")]
    assert any("accento" in r and "2" in r for r in fuori_tabella)
    assert any("apostrofo" in r and "1" in r for r in fuori_tabella)


def test_render_report_sezione_rifiutate_con_il_motivo():
    report = render_report(*_report_completo())
    assert "## Rifiutate" in report
    assert "## Dubbi (non modificati)" in report
    inizio = report.index("## Rifiutate")
    fine = report.index("## Dubbi (non modificati)")
    assert inizio < fine
    sezione = report[inizio:fine]
    assert "incantevole" in sezione
    assert "categoria non ammessa" in sezione


def test_render_report_sezione_dubbi_con_fragment_e_note():
    report = render_report(*_report_completo())
    sezione = report[report.index("## Dubbi (non modificati)"):]
    assert DUBBIO["fragment"] in sezione
    assert DUBBIO["note"] in sezione


def test_render_report_il_pipe_nei_testi_non_rompe_la_tabella():
    accepted = [
        E("1", "e|o", "e o", "refuso", "vedi a | b nel testo"),
        E("2", "perche", "perché", "accento", "motivo normale"),
    ]
    report = render_report(accepted, [], [])
    righe = [r for r in report.split("## Rifiutate")[0].splitlines() if r.lstrip().startswith("|")]
    assert len(righe) >= 4  # intestazione, separatore, due righe di dati
    celle = {len(re.findall(r"(?<!\\)\|", r)) for r in righe}
    assert len(celle) == 1, f"numero di celle diverso tra le righe: {righe}"
    assert any("vedi a" in r for r in righe)


# --------------------------------------------------------------------------
# Funzioni pure
# --------------------------------------------------------------------------

def test_le_funzioni_non_modificano_gli_argomenti():
    text = "Ha un'amico, non sappiamo perche e incantevole resta."
    edits = [
        E("1", "un'amico", "un amico", "apostrofo"),
        E("2", "perche", "perché", "accento"),
        E("3", "incantevole", "bella", "stile"),
    ]
    protected = ["resta"]
    doubts = [dict(DUBBIO)]
    edits_prima = copy.deepcopy(edits)
    protected_prima = copy.deepcopy(protected)
    doubts_prima = copy.deepcopy(doubts)

    accepted, rejected = validate_edits(text, edits, protected=protected)
    assert edits == edits_prima and protected == protected_prima

    accepted_prima = copy.deepcopy(accepted)
    rejected_prima = copy.deepcopy(rejected)
    corrected = apply_edits(text, accepted)
    only_listed_changes(text, corrected, accepted)
    render_report(accepted, rejected, doubts)

    assert accepted == accepted_prima
    assert rejected == rejected_prima
    assert doubts == doubts_prima
    assert text == "Ha un'amico, non sappiamo perche e incantevole resta."
