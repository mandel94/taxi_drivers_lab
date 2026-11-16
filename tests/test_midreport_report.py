"""
tests/test_midreport_report.py

Contratto di ga4_client/midreport_report.py (nlp/midreport_style/CONTRATTO.md).
Funzioni pure: DataFrame finti, nessun DB, nessun GA4, nessuna rete.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_midreport_report.py
"""

import datetime as dt
import pathlib
import re
import sys

import pandas as pd
import pytest
from openpyxl import load_workbook

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ga4_client"))

from midreport_report import (  # noqa: E402
    CATEGORY_ORDER,
    build_notes,
    build_sections,
    category_stats,
    format_item,
    format_note,
    reliability_warning,
    render_html,
    subject,
    week_label,
    write_classifica_xlsx,
)

ARROW = "→"
EXCLUDED = "I migliori siti di film streaming gratis in italia"


def _row(title, category, score, users, rate=0.5, dur=30.0, pages=100,
         author="Autore", date=dt.datetime(2026, 11, 3)):
    return {
        "title": title,
        "editorial_score": score,
        "publication_date": date,
        "author": author,
        "category": category,
        "activeUsers": users,
        "screenPageViews": pages,
        "engagementRate": rate,
        "averageSessionDuration": dur,
    }


def _df(rows):
    return pd.DataFrame(rows)


# --- CATEGORY_ORDER -------------------------------------------------------

def test_category_order():
    assert list(CATEGORY_ORDER) == [
        "Si farà", "Serie TV", "Live Streaming On Demand", "News",
        "Festival di Cinema", "Speciali e Magazine", "Interviste",
        "Recensioni", "Anticipazioni", "Trailers",
    ]


# --- week_label / subject -------------------------------------------------

def test_week_label_same_month():
    assert week_label(dt.date(2026, 11, 2), dt.date(2026, 11, 6)) == "2-6 nov 2026"


def test_week_label_across_months():
    assert week_label(dt.date(2026, 10, 28), dt.date(2026, 11, 1)) == "28 ott - 1 nov 2026"


def test_subject_iso_week():
    assert subject(dt.date(2026, 11, 2), dt.date(2026, 11, 6)) == (
        "TaxiDrivers Analytics: Midreport Settimana 45 (2-6 nov 2026)"
    )


# --- build_sections -------------------------------------------------------

def _sections_df():
    rows = [
        _row("N1", "News", 50, 10),
        _row("N2", "News", 90, 10),
        _row("N3", "News", 70, 10),
        _row("N4", "News", 80, 10),
        _row(EXCLUDED, "News", 99, 10),
        _row("S1", "Serie TV", 40, 10),
        _row("Z1", "Categoria sconosciuta", 95, 10),
        _row("T1", "Trailers", 10, 10),
    ]
    return _df(rows)


def test_build_sections_top_per_cat_sorted_and_excluded():
    sections = build_sections(_sections_df())
    assert [r["title"] for r in sections["News"]] == ["N2", "N4", "N3"]
    assert [r["title"] for r in sections["Serie TV"]] == ["S1"]


def test_build_sections_order_and_omitted_categories():
    sections = build_sections(_sections_df())
    assert list(sections.keys()) == ["Serie TV", "News", "Trailers"]
    assert "Categoria sconosciuta" not in sections
    assert "Interviste" not in sections


def test_build_sections_per_cat_param():
    sections = build_sections(_sections_df(), per_cat=1)
    assert [r["title"] for r in sections["News"]] == ["N2"]


# --- build_notes ----------------------------------------------------------

def _notes_df():
    rows = [
        # News: il piu' letto (200) sta fuori dalla sezione
        _row("N1", "News", 90, 10),
        _row("N2", "News", 80, 20),
        _row("N3", "News", 70, 30),
        _row("N-nota", "News", 10, 200),
        # Serie TV: il piu' letto e' gia' in sezione
        _row("S1", "Serie TV", 90, 300),
        _row("S2", "Serie TV", 80, 10),
        # Interviste: il piu' letto fuori sezione ha solo 30 utenti
        _row("I1", "Interviste", 90, 10),
        _row("I2", "Interviste", 80, 10),
        _row("I3", "Interviste", 70, 10),
        _row("I-poco", "Interviste", 5, 30),
    ]
    return _df(rows)


def test_build_notes_only_outside_sections_above_threshold():
    df = _notes_df()
    sections = build_sections(df)
    notes = build_notes(df, sections)
    assert notes["News"]["title"] == "N-nota"
    assert "Serie TV" not in notes
    assert "Interviste" not in notes


def test_build_notes_min_users_param():
    df = _notes_df()
    sections = build_sections(df)
    notes = build_notes(df, sections, min_users=20)
    assert notes["Interviste"]["title"] == "I-poco"


# --- category_stats -------------------------------------------------------

def _stats_as_dict(result):
    if isinstance(result, dict):
        return result
    if isinstance(result, pd.Series):
        return result.to_dict()
    if "category" in result.columns:
        result = result.set_index("category")
    return result.iloc[:, 0].to_dict()


def test_category_stats_shares_sum_to_100_and_skip_excluded():
    df = _df([
        _row("N1", "News", 50, 60),
        _row("S1", "Serie TV", 50, 40),
        _row(EXCLUDED, "News", 50, 900),
    ])
    stats = _stats_as_dict(category_stats(df))
    assert stats["News"] == pytest.approx(60.0, abs=0.1)
    assert stats["Serie TV"] == pytest.approx(40.0, abs=0.1)
    assert sum(stats.values()) == pytest.approx(100.0, abs=0.1)


# --- format_item / format_note -------------------------------------------

def test_format_item():
    row = _row("Titolo", "News", 71.4, 18.2, rate=0.79, dur=47.3)
    assert format_item(row) == (
        f"'Titolo' (score: 71) {ARROW} 18 utenti attivi, 79% engagement, 47s."
    )


def test_format_note():
    row = _row("Titolo", "News", 62.2, 130.8, rate=0.52, dur=64.4)
    assert format_note(row) == (
        f"Nota: 'Titolo' (score: 62, 131 utenti attivi) {ARROW} 52% engagement, 64s."
    )


# --- render_html ----------------------------------------------------------

def _render(sintesi=None, sections=None, notes=None, chart="Il grafico mostra la quota."):
    if sections is None:
        sections = {"News": [_row("Titolo uno", "News", 71, 18, rate=0.79, dur=47)]}
    if notes is None:
        notes = {}
    return render_html(
        dt.date(2026, 11, 2), dt.date(2026, 11, 6),
        sintesi if sintesi is not None else ["Prima sintesi", "Seconda sintesi"],
        sections, notes, chart,
    )


def test_render_html_structure_and_greeting():
    html = _render()
    assert "Ciao Sandra, ciao Vincenzo, ciao Gianluca," in html
    assert "vi mando il midreport per la settimana 45 (dal 2 al 6" in html
    assert "In sintesi:" in html
    assert "<ul>" in html and html.count("<li>") >= 2
    assert "Prima sintesi" in html and "Seconda sintesi" in html
    assert "<b>News:</b>" in html
    assert "<i>Titolo uno</i>" in html
    assert "Il grafico mostra la quota." in html
    assert "Una buona serata," in html


def test_render_html_gmail_constraints_and_signature():
    html = _render()
    low = html.lower()
    assert "<style" not in low
    assert "<html" not in low
    assert "views" not in low
    assert "Manuel De Luzi" in html
    assert "linkedin" in low
    assert "linktree" in low
    assert '/mannyotc" style=' in html and '/manuel-de-luzi/" style=' in html
    assert 'style="' in html


def test_render_html_items_are_bulleted_paragraphs_and_notes_separate():
    sections = {"News": [_row("Titolo uno", "News", 71, 18), _row("Titolo due", "News", 70, 17)]}
    notes = {"News": _row("Titolo nota", "News", 60, 90)}
    html = _render(sections=sections, notes=notes)
    assert re.search(r"<p[^>]*>• <i>Titolo uno</i>[^<]*</p>", html)
    assert re.search(r"<p[^>]*>• <i>Titolo due</i>[^<]*</p>", html)
    assert re.search(r"<p[^>]*>Nota: <i>Titolo nota</i>", html)
    assert "<br" not in html


def test_render_html_escapes_text():
    sections = {"News": [_row("Tom & Jerry <3", "News", 71, 18)]}
    html = _render(sintesi=["A & B <script>"], sections=sections)
    assert "Tom &amp; Jerry &lt;3" in html
    assert "A &amp; B &lt;script&gt;" in html
    assert "<script>" not in html
    assert "Jerry <3" not in html


# --- write_classifica_xlsx ------------------------------------------------

def _xlsx_df():
    return _df([
        _row("Basso", "News", 50, 10, date=dt.datetime(2026, 11, 2)),
        _row("Alto", "Serie TV", 60, 300, date=dt.datetime(2026, 11, 3)),
        _row(EXCLUDED, "News", 70, 999),
        _row("Medio", "News", 40, 120, date=dt.datetime(2026, 11, 4)),
    ])


def test_write_classifica_xlsx_sheet_headers_table_freeze(tmp_path):
    path = tmp_path / "classifica_articoli_week 45.xlsx"
    write_classifica_xlsx(_xlsx_df(), path)
    wb = load_workbook(path)
    ws = wb["Dati"]
    headers = [c.value for c in ws[1]]
    assert headers == [
        "title", "editorial_score", "publication_date", "author",
        "category", "activeUsers", "engagementRate", "averageSessionDuration",
    ]
    assert ws.tables["Tabella2"].ref == "A1:H4"  # 3 righe dati (1 esclusa)
    assert ws.freeze_panes == "D1"


def test_write_classifica_xlsx_order_exclusions_and_dates(tmp_path):
    path = tmp_path / "classifica_articoli_week 45.xlsx"
    write_classifica_xlsx(_xlsx_df(), path)
    ws = load_workbook(path)["Dati"]
    titles = [ws.cell(row=r, column=1).value for r in range(2, ws.max_row + 1)]
    assert titles == ["Alto", "Medio", "Basso"]
    for r in range(2, ws.max_row + 1):
        assert isinstance(ws.cell(row=r, column=3).value, dt.datetime)


# --- reliability_warning --------------------------------------------------

def test_reliability_warning_before_incident():
    assert reliability_warning(dt.date(2026, 11, 6)) is None


@pytest.mark.parametrize("end", [dt.date(2026, 11, 10), dt.date(2026, 11, 13)])
def test_reliability_warning_from_incident(end):
    msg = reliability_warning(end)
    assert isinstance(msg, str) and msg


# --- kb_filename / write_kb_xlsx (CONTRATTO_STORICO.md, sezione B) --------

def test_kb_filename():
    from midreport_report import kb_filename
    assert kb_filename(dt.date(2026, 11, 2), dt.date(2026, 11, 6)) == (
        "top_articles_by_category_20261102_20261106.xlsx"
    )


def _kb_df():
    rows = [
        _row("Basso", "News", 50, 10, date=dt.datetime(2026, 11, 2)),
        _row("Alto", "Serie TV", 60, 300, date=dt.datetime(2026, 11, 3)),
        _row(EXCLUDED, "News", 70, 999),
        _row("Medio", "News", 40, 120, date=dt.datetime(2026, 11, 4)),
    ]
    for row, article_id in zip(rows, [101, 102, 103, 104]):
        row["article_id"] = article_id
    return _df(rows)


def test_write_kb_xlsx_headers_pagepath_order_exclusions(tmp_path):
    from midreport_report import write_kb_xlsx
    path = tmp_path / "top_articles_by_category_20261102_20261106.xlsx"
    write_kb_xlsx(_kb_df(), path)
    wb = load_workbook(path)
    assert len(wb.sheetnames) == 1
    ws = wb[wb.sheetnames[0]]
    assert [c.value for c in ws[1]] == [
        "title", "editorial_score", "publication_date", "author", "category",
        "activeUsers", "screenPageViews", "engagementRate",
        "averageSessionDuration", "pagePath",
    ]
    assert ws.max_row == 4  # intestazione + 3 righe (1 titolo escluso)
    titles = [ws.cell(row=r, column=1).value for r in range(2, 5)]
    paths = [ws.cell(row=r, column=10).value for r in range(2, 5)]
    assert titles == ["Alto", "Medio", "Basso"]
    assert paths == ["/102/", "/104/", "/101/"]
