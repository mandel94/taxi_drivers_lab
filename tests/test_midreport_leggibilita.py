"""
tests/test_midreport_leggibilita.py

Misura di leggibilita' dei testi del midreport (nlp/midreport_insight/leggibilita.py): indice
Gulpease (pensato per l'italiano) piu' regole semplici: frasi corte, pochi numeri, poche
parentesi, niente gergo statistico. render ha un controllo che rifiuta i testi illeggibili.

Esecuzione: python -m pytest -q tests/test_midreport_leggibilita.py
"""

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "ga4_client"))

from nlp.midreport_insight import leggibilita as lg  # noqa: E402

SEMPLICE = ("Le guide mensili vanno bene a fine mese. Quella di novembre ha fatto 70 utenti. "
            "Per dicembre conviene pubblicarle tutte insieme.")
ILLEGGIBILE = ("Un pezzo nuovo vive nella settimana d'uscita: dei 175 usciti nei primi tre giorni con almeno 15 "
               "utenti, solo il 26% è ancora in lista la settimana dopo e fanno il 18% dei lettori della prima "
               "(vale per tutte e cinque le coppie di settimane; Festival 17% su 58 pezzi). La spinta (home, "
               "social, newsletter) va nel giorno d'uscita. Si farà, Trailers e Live Streaming On Demand "
               "resistono di più (53-70%, 9-15 pezzi ciascuno): lì conviene aggiornare l'articolo esistente.")


def test_gulpease_formula_and_clamp():
    assert lg.gulpease("Il gatto dorme.") == 100.0  # 149 limitato a 100
    # 3 parole, 31 lettere (l'apostrofo non e' una lettera), 1 frase: 89 + (300 - 310) / 3
    assert lg.gulpease("Abbiamo constatato un'incongruenza.") == pytest.approx(85.7, abs=0.1)


def test_sentence_split_ignores_decimal_and_thousand_separators():
    assert lg.check("Sono 2.334 utenti. Il 9,9% legge.")["sentences"] == 2


def test_simple_text_passes():
    r = lg.check(SEMPLICE)
    assert r["ok"] and r["problems"] == [] and r["gulpease"] >= 60


def test_unreadable_text_is_flagged_with_reasons():
    r = lg.check(ILLEGGIBILE)
    assert not r["ok"]
    joined = " ".join(r["problems"])
    assert "numeri" in joined and "parentesi" in joined and "frase" in joined


@pytest.mark.parametrize("word", ["mediana", "coorte", "baseline", "pattern", "confondente", "reach", "z = 4,1"])
def test_statistical_jargon_is_flagged(word):
    r = lg.check(f"Questa settimana il valore è {word} e va letto con calma.")
    assert any("gergo" in p and word.split()[0] in p for p in r["problems"])


def test_check_sintesi_reports_index_of_bad_bullets():
    out = lg.check_sintesi([SEMPLICE, ILLEGGIBILE])
    assert [i for i, _ in out] == [1]


def test_render_refuses_unreadable_text(tmp_path, monkeypatch):
    import midreport_render

    monkeypatch.setenv("TD_LEGGIBILITA_DATI", str(tmp_path / "dati"))  # il registro delle lezioni resta in tmp

    (tmp_path / "dati.json").write_text(json.dumps({"start": "2026-11-02", "end": "2026-11-06",
                                                    "sections": {}, "notes": {}}), encoding="utf-8")
    red = {"sintesi": [ILLEGGIBILE], "chart_sentence": "Grafico."}
    path = tmp_path / "redazione.json"
    path.write_text(json.dumps(red), encoding="utf-8")
    assert midreport_render.main(["--dir", str(tmp_path), "--redazione", str(path)]) == 2
    assert not list(tmp_path.glob("midreport_settimana*.html"))
    assert midreport_render.main(["--dir", str(tmp_path), "--redazione", str(path), "--no-check"]) == 0
    red["sintesi"] = [SEMPLICE]
    path.write_text(json.dumps(red), encoding="utf-8")
    assert midreport_render.main(["--dir", str(tmp_path), "--redazione", str(path)]) == 0
