"""
tests/test_midreport_storico.py

Contratto di ga4_client/midreport_storico.py (nlp/midreport_style/CONTRATTO_STORICO.md, sezione A).
Funzioni pure: dati finti, cartelle in tmp_path, nessun DB, nessuna rete.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_midreport_storico.py
"""

import csv
import datetime as dt
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ga4_client"))

from midreport_storico import (  # noqa: E402
    build_record,
    items_rows,
    load_weeks,
    parse_sent_report,
    upsert_week,
)

ITEMS_COLUMNS = [
    "week_id", "category", "kind", "rank", "title",
    "score", "users", "engagement", "duration_s", "metric",
]


def _row(title, score, users, rate=0.5, dur=30.0):
    return {
        "title": title,
        "editorial_score": score,
        "activeUsers": users,
        "engagementRate": rate,
        "averageSessionDuration": dur,
    }


def _record(start=dt.date(2026, 11, 2), subject="Oggetto", **kw):
    sections = {
        "News": [_row("Perché uno", 71, 18, 0.79, 47), _row("Titolo due", 70, 17, 0.7, 40)],
        "Serie TV": [_row("Serie uno", 65, 30, 0.6, 35)],
    }
    notes = {"News": _row("Titolo nota", 62, 131, 0.52, 64)}
    return build_record(
        start, start + dt.timedelta(days=4), subject,
        ["Prima sintesi", "Seconda sintesi"], sections, notes, **kw,
    )


# --- build_record ---------------------------------------------------------

def test_build_record_fields_and_reduced_sections():
    rec = _record(chart_sentence="Il trend.", n_articles=42,
                  drive_folder_id="drv", gmail_draft_id="drf")
    assert rec["week_id"] == "2026-11-02"
    assert str(rec["period_start"]) == "2026-11-02"
    assert str(rec["period_end"]) == "2026-11-06"
    assert int(rec["iso_week"]) == 45
    assert rec["subject"] == "Oggetto"
    assert rec["sintesi"] == ["Prima sintesi", "Seconda sintesi"]
    assert rec["chart_sentence"] == "Il trend."
    assert rec["n_articles"] == 42
    assert rec["drive_folder_id"] == "drv"
    assert rec["gmail_draft_id"] == "drf"
    assert rec["sections"]["News"][0] == {
        "title": "Perché uno", "score": 71, "users": 18,
        "engagement": 0.79, "duration_s": 47,
    }
    assert [r["title"] for r in rec["sections"]["News"]] == ["Perché uno", "Titolo due"]
    assert rec["notes"]["News"] == [{
        "title": "Titolo nota", "score": 62, "users": 131,
        "engagement": 0.52, "duration_s": 64,
    }]


def test_build_record_defaults():
    rec = _record()
    assert rec["insights"] == []
    assert rec["metric"] == "utenti"
    assert rec["source"] == "workflow"
    assert rec["reliability_warning"] is None
    assert rec["category_stats"] is None
    assert rec["gmail_draft_id"] is None


# --- items_rows -----------------------------------------------------------

def test_items_rows_items_and_notes():
    rows = items_rows(_record())
    assert all(list(r.keys()) == ITEMS_COLUMNS for r in rows)
    assert len(rows) == 4
    news = [r for r in rows if r["category"] == "News" and r["kind"] == "item"]
    assert [(r["rank"], r["title"]) for r in news] == [(1, "Perché uno"), (2, "Titolo due")]
    first = news[0]
    assert first["week_id"] == "2026-11-02"
    assert (first["score"], first["users"], first["engagement"], first["duration_s"]) == (71, 18, 0.79, 47)
    assert first["metric"] == "utenti"
    nota = [r for r in rows if r["kind"] == "nota"]
    assert len(nota) == 1
    assert nota[0]["category"] == "News"
    assert nota[0]["rank"] == 0
    assert nota[0]["title"] == "Titolo nota"
    assert nota[0]["users"] == 131


# --- upsert_week / load_weeks --------------------------------------------

def test_upsert_week_creates_files_utf8_lf(tmp_path):
    folder = tmp_path / "midreports"
    path = upsert_week(folder, _record())
    assert pathlib.Path(path) == folder / "midreports.jsonl"
    csv_path = folder / "midreport_items.csv"
    assert csv_path.exists()
    for p in (pathlib.Path(path), csv_path):
        raw = p.read_bytes()
        assert b"\r" not in raw
        assert raw.endswith(b"\n")
        raw.decode("utf-8")
    assert csv_path.read_text(encoding="utf-8").splitlines()[0] == ",".join(ITEMS_COLUMNS)


def test_upsert_week_is_idempotent(tmp_path):
    folder = tmp_path / "midreports"
    upsert_week(folder, _record(subject="Primo"))
    path = upsert_week(folder, _record(subject="Secondo"))
    lines = pathlib.Path(path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["subject"] == "Secondo"
    with open(folder / "midreport_items.csv", encoding="utf-8", newline="") as f:
        assert len(list(csv.DictReader(f))) == 4


def test_upsert_week_orders_by_week_id(tmp_path):
    folder = tmp_path / "midreports"
    upsert_week(folder, _record(start=dt.date(2026, 11, 9)))
    path = upsert_week(folder, _record(start=dt.date(2026, 11, 2)))
    ids = [json.loads(line)["week_id"]
           for line in pathlib.Path(path).read_text(encoding="utf-8").splitlines()]
    assert ids == ["2026-11-02", "2026-11-09"]
    with open(folder / "midreport_items.csv", encoding="utf-8", newline="") as f:
        assert len(list(csv.DictReader(f))) == 8


def test_load_weeks_sorted_and_empty(tmp_path):
    folder = tmp_path / "midreports"
    assert load_weeks(folder) == []
    upsert_week(folder, _record(start=dt.date(2026, 11, 9)))
    upsert_week(folder, _record(start=dt.date(2026, 11, 2)))
    weeks = load_weeks(folder)
    assert [w["week_id"] for w in weeks] == ["2026-11-02", "2026-11-09"]
    assert weeks[0]["sections"]["News"][0]["title"] == "Perché uno"


# --- parse_sent_report ----------------------------------------------------

NEW_FORMAT = """\
Ciao Sandra, ciao Vincenzo, ciao Gianluca,
vi mando il midreport per la settimana 45 (dal 2 al 6 novembre 2026).

*In sintesi:*
• Prima sintesi che va
  a capo.
• Seconda sintesi.

*Serie TV:*
• 'Serie A' (score: 71) → 18 utenti attivi, 79% engagement, 47s.
• 'Serie B' (score: 70) → 17 utenti attivi, 70% engagement, 40s.
• 'Serie C' (score: 65) →
  16 utenti attivi, 60% engagement, 35s.

*News:*
• 'News A' (score: 80) → 50 utenti attivi, 55% engagement, 50s.
• 'News B' (score: 75) → 40 utenti attivi, 50% engagement, 45s.
• 'News C' (score: 74) → 30 utenti attivi, 45% engagement, 44s.
Nota: 'News Nota' (score: 62, 131 utenti attivi) → 52% engagement, 64s.

Il grafico mostra il trend delle quote per categoria.

Una buona serata,
Manuel
"""

OLD_FORMAT = """\
TaxiDrivers Analytics: Midreport Settimana 45 (2-6 novembre 2026)

Ciao a tutti,
ecco il midreport.

In sintesi:
• Sintesi vecchia uno.
• Sintesi vecchia due.

Serie TV:
• 'Vecchia A' (score: 71.4) → 18 views, 79% engagement, 47s.
• 'Vecchia B' (score: 70.2) → 17 views, 70% engagement, 40s.
• 'Vecchia C' (score: 65.8) → 16 views, 60% engagement, 35s.

News:
• 'Notizia A' (score: 80.5) → 50 views, 55% engagement, 50s.
• 'Notizia B' (score: 75.1) → 40 views, 50% engagement, 45s.
• 'Notizia C' (score: 74.9) → 30 views, 45% engagement, 44s.
Nota: 'Notizia Nota' (score: 62.2, 131 views) → 52% engagement, 64s.

Il trend delle categorie e' stabile.

Una buona serata,
Manuel
"""


def test_parse_sent_report_new_format():
    rec = parse_sent_report(NEW_FORMAT, dt.date(2026, 11, 9))
    assert rec["source"] == "gmail"
    assert rec["metric"] == "utenti"
    assert rec["week_id"] == "2026-11-02"
    assert str(rec["period_start"]) == "2026-11-02"
    assert str(rec["period_end"]) == "2026-11-06"
    assert rec["sintesi"] == ["Prima sintesi che va a capo.", "Seconda sintesi."]
    assert list(rec["sections"].keys()) == ["Serie TV", "News"]
    assert [r["title"] for r in rec["sections"]["Serie TV"]] == ["Serie A", "Serie B", "Serie C"]
    assert [r["title"] for r in rec["sections"]["News"]] == ["News A", "News B", "News C"]
    third = rec["sections"]["Serie TV"][2]
    assert (third["score"], third["users"], third["duration_s"]) == (65, 16, 35)
    assert third["engagement"] == pytest.approx(0.60)
    assert "Serie TV" not in rec["notes"]
    nota = rec["notes"]["News"]
    assert len(nota) == 1
    assert nota[0]["title"] == "News Nota"
    assert nota[0]["users"] == 131
    assert nota[0]["engagement"] == pytest.approx(0.52)
    assert "trend" in rec["chart_sentence"]


def test_parse_sent_report_old_format():
    rec = parse_sent_report(OLD_FORMAT, dt.date(2026, 11, 9))
    assert rec["source"] == "gmail"
    assert rec["metric"] == "views"
    assert rec["week_id"] == "2026-11-02"
    assert str(rec["period_end"]) == "2026-11-06"
    assert rec["sintesi"] == ["Sintesi vecchia uno.", "Sintesi vecchia due."]
    assert list(rec["sections"].keys()) == ["Serie TV", "News"]
    assert [r["title"] for r in rec["sections"]["Serie TV"]] == ["Vecchia A", "Vecchia B", "Vecchia C"]
    assert [r["title"] for r in rec["sections"]["News"]] == ["Notizia A", "Notizia B", "Notizia C"]
    first = rec["sections"]["Serie TV"][0]
    assert first["score"] == pytest.approx(71.4)
    assert first["users"] == 18
    assert first["engagement"] == pytest.approx(0.79)
    assert "Serie TV" not in rec["notes"]
    assert rec["notes"]["News"][0]["title"] == "Notizia Nota"
    assert rec["notes"]["News"][0]["users"] == 131
    assert "trend" in rec["chart_sentence"]


def test_parse_sent_report_real_gmail_format_title_without_closing_quote_and_signature():
    import datetime as _dt
    text = (
        "Ciao Sandra, ciao Vincenzo, ciao Gianluca,\n\n"
        "vi mando il midreport per la settimana 45 (dal 2 al 6 nov).\n\n"
        "In sintesi:\n\n"
        "   - Primo punto con *Lupin 5*\n   che va a capo.\n"
        "   - Secondo punto.\n\n"
        "*Si farà:*\n\n"
        "• *'Sullivan's Crossing 5' è ufficiale: la serie avrà una quinta stagione*\n"
        "(score: 71) → 18 utenti attivi, 79% engagement, 47s.\n\n"
        "Nota: *'Lupin 5' si farà? Il futuro della serie Netflix* (score: 62, 131\n"
        "utenti attivi) → 52% engagement, 64s. Più letto della settimana.\n\n"
        "Qui sotto trovate il trend delle visualizzazioni, in crescita.\n"
        "[image: newplot (5).png]Una buona serata,\nManuel De Luzi\n--\nLinkedIn: https://x\n"
    )
    r = parse_sent_report(text, _dt.date(2026, 11, 9))
    assert r["sintesi"][0] == "Primo punto con Lupin 5 che va a capo."
    item = r["sections"]["Si farà"][0]
    assert item["title"].startswith("'Sullivan's Crossing 5' è ufficiale")
    assert item["users"] == 18
    assert r["notes"]["Si farà"][0]["users"] == 131
    assert r["chart_sentence"] == "Qui sotto trovate il trend delle visualizzazioni, in crescita."

def test_parse_sent_report_variants_ascii_arrow_in_breve_and_bullets_without_header():
    import datetime as _dt
    ascii_arrow = (
        "Ciao Sandra, ciao Vincenzo,\n\n"
        "vi mando il midreport per la settimana 29 (13-19 lug 2026).\n\n"
        "*In breve:*\n\n   - Primo punto.\n   - Secondo punto.\n\n"
        "*Si farà:*\n"
        "• 'Bocciato 2': Seconda Stagione In Arrivo? (score: 66) -> 47 views, 45%\n"
        "engagement, 123s.\n"
    )
    r = parse_sent_report(ascii_arrow, _dt.date(2026, 7, 20))
    assert r["sintesi"] == ["Primo punto.", "Secondo punto."]
    assert r["metric"] == "views"
    assert r["sections"]["Si farà"][0]["users"] == 47
    no_header = (
        "Ciao Sandra, ciao Vincenzo,\n\n"
        "vi mando il midreport per la settimana 22 (dal 22 al 31 maggio). In breve:\n\n"
        "   - Un punto senza intestazione.\n\n"
        "*Si farà:*\n"
        "• 'X': Y (score: 58.05) → 220 views, 50% engagement, 58s.\n"
    )
    r = parse_sent_report(no_header, _dt.date(2026, 6, 2))
    assert r["sintesi"] == ["Un punto senza intestazione."]
    assert "Si farà" in r["sections"]


def test_parse_sent_report_free_prose_becomes_sintesi():
    import datetime as _dt
    prose = (
        "Ciao Sandra,\ntrovi qui il mid-report per la settimana appena trascorsa.\n\n"
        "*'The Great' 4* porta ancora traffico,\nconfermandosi caso di successo.\n\n"
        "Tra le anticipazioni va bene Fallout 2.\n\n"
        "Una buona giornata!\nManuel De Luzi\n--\nLinkedIn: https://x\n"
    )
    r = parse_sent_report(prose, _dt.date(2025, 12, 22))
    assert r["sections"] == {}
    assert r["sintesi"] == [
        "'The Great' 4 porta ancora traffico, confermandosi caso di successo.",
        "Tra le anticipazioni va bene Fallout 2.",
    ]

def test_parse_sent_report_en_dash_period_glued_header_and_colon_continuation():
    import datetime as _dt
    text = (
        "Ciao Sandra, ciao Vincenzo,\n\n"
        "torno col midreport per la settimana 35 (24–28 ago 2026).\n\n"
        "In sintesi:\n\n"
        "   - Punto che va a capo con un\n   coinvolgimento:\n   alto.\n\n"
        "*Si farà:*• 'Sullivan's Crossing 5' È Ufficiale (score: 69) → 66 views, 46% engagement, 144s.\n"
        "• 'Outer Banks 6' Non Si Farà (score: 74) → 43 views, 79% engagement.\n"
    )
    r = parse_sent_report(text, _dt.date(2026, 8, 29))
    assert (r["period_start"], r["period_end"]) == ("2026-08-24", "2026-08-28")
    assert list(r["sections"]) == ["Si farà"]
    assert [i["users"] for i in r["sections"]["Si farà"]] == [66, 43]
    assert r["sections"]["Si farà"][1]["duration_s"] is None
    assert r["sintesi"] == ["Punto che va a capo con un coinvolgimento: alto."]