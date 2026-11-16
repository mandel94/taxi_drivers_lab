"""
tests/test_leggibilita_modulo.py

Modulo nlp/leggibilita: misura (Gulpease e regole), ciclo di miglioramento (correzioni
meccaniche e diagnosi di cio' che resta da riscrivere) e lezioni (registro degli eventi,
feedback, documento centrale docs/leggibilita.md). Nessuna rete, nessuna scrittura fuori da tmp_path.

Esecuzione: python -m pytest -q tests/test_leggibilita_modulo.py
"""

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nlp.leggibilita import ciclo, lezioni, misura  # noqa: E402

GLOSSARIO = {"mediana": "cifra tipica", "baseline": "base di confronto", "pattern": "andamento"}
DIFFICILE = ("La mediana è 10; la baseline è 8 (dato A) e il pattern (dato B) si ripete ogni mese, "
             "come si vede dal grafico.")
MECCANICO = ("La cifra tipica è 10; la base di confronto è 8 (dato A) e l'andamento (dato B) si ripete ogni "
             "mese, come si vede dal grafico.")


def test_pulisci_toglie_markdown_e_codice():
    md = "## Titolo\n- **Fatto** il [file](docs/a.md) con `codice`\n- Seconda voce"
    assert misura.pulisci(md) == "Titolo. Fatto il file con. Seconda voce."


def test_glossary_terms_are_flagged_and_dictionary_is_shipped():
    r = misura.check("La mediana sale.", glossario=GLOSSARIO)
    assert any("gergo" in p and "mediana" in p for p in r["problems"])
    assert "coorte" in misura.carica_glossario()  # glossario di partenza


def test_migliora_applies_mechanical_fixes_and_reports_steps():
    out = ciclo.migliora(MECCANICO, glossario=GLOSSARIO)
    assert out["ok"] and out["testo"].count("(") <= 1
    assert out["iterazioni"][0]["problemi"] and out["iterazioni"][0]["azioni"]
    assert out["iterazioni"][-1]["problemi"] == []


def test_migliora_suggests_plain_words_but_does_not_rewrite_jargon():
    out = ciclo.migliora(DIFFICILE, glossario=GLOSSARIO)
    assert not out["ok"] and "mediana" in out["testo"]
    assert "sostituire 'mediana' con 'cifra tipica'" in out["da_riscrivere"]


def test_migliora_leaves_what_only_a_writer_can_fix():
    numeri = "Valori: 11, 22, 33, 44, 55, 66, 77, 88. Sono andati bene."
    out = ciclo.migliora(numeri, glossario=GLOSSARIO)
    assert not out["ok"] and out["testo"] == numeri
    assert any("numeri" in d for d in out["da_riscrivere"])


def test_garantisci_logs_event_and_learned_term_becomes_a_rule(tmp_path):
    dati = tmp_path / "dati"
    out = lezioni.garantisci(MECCANICO, origine="test", dati_dir=dati, glossario=GLOSSARIO)
    assert out["ok"]
    ev = [json.loads(r) for r in (dati / "eventi.jsonl").read_text(encoding="utf-8").splitlines()]
    assert ev[0]["tipo"] == "testo" and ev[0]["prima"] == MECCANICO and ev[0]["ok"] and ev[0]["problemi_prima"]
    # feedback dell'utente su un termine: finisce nel glossario e nel registro
    lezioni.feedback("non capisco 'coorte'", termine="coorte", semplice="gruppo", dati_dir=dati)
    assert misura.carica_glossario(dati / "glossario.json")["coorte"] == "gruppo"
    suggerimenti = ciclo.migliora("Una coorte di articoli.", glossario=misura.carica_glossario(dati / "glossario.json"))
    assert "sostituire 'coorte' con 'gruppo'" in suggerimenti["da_riscrivere"]


def test_documento_centrale_is_regenerated_from_events(tmp_path):
    dati = tmp_path / "dati"
    lezioni.garantisci(DIFFICILE, origine="test", dati_dir=dati, glossario=GLOSSARIO)
    lezioni.feedback("gli insight non si capiscono", dati_dir=dati)
    doc = tmp_path / "leggibilita.md"
    lezioni.aggiorna_documento(dati_dir=dati, out=doc)
    testo = doc.read_text(encoding="utf-8")
    first = testo
    assert "Gulpease" in testo and "gli insight non si capiscono" in testo
    assert "Problemi più frequenti" in testo and "gergo statistico" in testo
    lezioni.aggiorna_documento(dati_dir=dati, out=doc)
    assert doc.read_text(encoding="utf-8") == first  # idempotente


def test_cli_check_exit_codes_and_commands(tmp_path, monkeypatch, capsys):
    from nlp.leggibilita import __main__ as cli

    monkeypatch.setenv("TD_LEGGIBILITA_DATI", str(tmp_path / "dati"))
    ok = tmp_path / "ok.txt"
    ok.write_text("Le guide vanno bene a fine mese. Per dicembre conviene pubblicarle tutte insieme.", encoding="utf-8")
    ko = tmp_path / "ko.txt"
    ko.write_text(DIFFICILE, encoding="utf-8")
    assert cli.main(["check", "--file", str(ok)]) == 0
    assert cli.main(["check", "--file", str(ko)]) == 1
    assert "mediana" in capsys.readouterr().out
    assert cli.main(["migliora", "--file", str(ko), "--origine", "test"]) == 1
    assert cli.main(["riscritto", "--prima", str(ko), "--dopo", str(ok)]) == 0
    assert cli.main(["feedback", "non capisco la mediana", "--termine", "mediana", "--semplice", "cifra tipica"]) == 0
    doc = tmp_path / "doc.md"
    assert cli.main(["documento", "--out", str(doc)]) == 0
    assert "non capisco la mediana" in doc.read_text(encoding="utf-8")


def test_max_words_can_be_raised_for_long_documents():
    lungo = " ".join(["Il sito ha avuto più lettori."] * 20)
    assert any("testo lungo" in p for p in misura.check(lungo)["problems"])
    assert misura.check(lungo, max_words=200)["ok"]
