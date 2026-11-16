"""
tests/test_midreport_chart.py

Grafico degli utenti attivi giornalieri (ga4_client/midreport_chart.py) e le due novita'
di render_html: riga di nota sui dati e immagine in fondo.

Esecuzione: python -m pytest -q tests/test_midreport_chart.py
"""

import datetime as dt
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ga4_client"))

import midreport_chart as ch  # noqa: E402
import midreport_report as rep  # noqa: E402


def test_window_starts_on_monday_n_weeks_back():
    start, end = ch.window(dt.date(2026, 11, 6), weeks=7)
    assert start == dt.date(2026, 9, 21) and start.weekday() == 0
    assert end == dt.date(2026, 11, 6)


def test_parse_daily_sorts_converts_and_fills_gaps():
    raw = pd.DataFrame({"date": ["20261103", "20261101", "20261102"], "activeUsers": ["30", "10", "20"]})
    out = ch.parse_daily(raw)
    assert list(out["users"]) == [10, 20, 30]
    assert out["date"].iloc[0] == pd.Timestamp("2026-11-01")
    gap = ch.parse_daily(raw.iloc[[0, 1]])  # manca il 2 novembre
    assert len(gap) == 3 and pd.isna(gap.loc[gap["date"] == pd.Timestamp("2026-11-02"), "users"].iloc[0])


def test_plot_writes_png(tmp_path):
    days = pd.date_range("2026-10-26", "2026-11-15")
    df = pd.DataFrame({"date": days, "users": range(2000, 2000 + len(days))})
    out = tmp_path / "newplot.png"
    ch.plot_daily_users(df, out, marked_days=[dt.date(2026, 11, 10)])
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 5000


def test_render_html_note_and_image():
    html = rep.render_html(dt.date(2026, 11, 2), dt.date(2026, 11, 6), ["a"], {}, {}, "Frase grafico.",
                           note_dati="Sei articoli con traffico automatico tolti.", chart_src="cid:grafico")
    assert "Nota sui dati: Sei articoli con traffico automatico tolti." in html
    assert html.index("Nota sui dati") < html.index("Frase grafico.") < html.index('<img src="cid:grafico"')
    assert html.index('<img src="cid:grafico"') < html.index("Una buona serata")


def test_render_html_without_new_args_has_no_image_or_note():
    html = rep.render_html(dt.date(2026, 11, 2), dt.date(2026, 11, 6), ["a"], {}, {}, "Frase.")
    assert "<img" not in html and "Nota sui dati" not in html
