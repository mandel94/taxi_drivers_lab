"""
tests/test_midreport_insight_azionabili.py

Osservazioni da cui nascono le azioni (nlp/midreport_insight/azionabili.py): vita degli articoli
nuovi, coda lunga dei pezzi nuovi, guide mensili delle piattaforme. Nessuna rete.

Esecuzione: python -m pytest -q tests/test_midreport_insight_azionabili.py
"""

import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from nlp.midreport_insight import azionabili as az  # noqa: E402
from nlp.midreport_insight import observe  # noqa: E402


def row(week, aid, title, cat, pub, users, comparable=True, er=0.6, dur=90.0):
    start = pd.Timestamp(week)
    return {"week_id": week, "period_start": week, "period_end": (start + pd.Timedelta(days=4)).strftime("%Y-%m-%d"),
            "window_days": 5, "comparable": comparable, "article_id": aid, "title": title, "author": "A",
            "category": cat, "pub_date": pub, "users": users, "er": er, "dur": dur, "excluded": False}


def history():
    rows = []
    # settimana 1: 10 pezzi usciti martedi' con 20 utenti; 4 compaiono ancora la settimana dopo, con 10
    for i in range(10):
        rows.append(row("2026-10-05", i, f"Pezzo {i}", "News", "2026-10-06", 20))
    for i in range(4):
        rows.append(row("2026-10-12", i, f"Pezzo {i}", "News", "2026-10-06", 10))
    # un pezzo uscito giovedi' (fuori dalla coorte) e uno con meno di 15 utenti (fuori)
    rows.append(row("2026-10-05", 50, "Tardivo", "News", "2026-10-08", 40))
    rows.append(row("2026-10-05", 51, "Piccolo", "News", "2026-10-06", 9))
    # settimana non contigua o non comparabile: ignorata
    rows.append(row("2026-10-26", 60, "Altro", "News", "2026-10-27", 30, comparable=False))
    return pd.DataFrame(rows)


def test_lifecycle_survival_and_retention():
    out = az.lifecycle(history(), min_users=15, min_cat=8)
    assert out["n"] == 10 and out["pairs"] == 1
    assert out["survival_pct"] == 40.0
    assert out["retained_pct"] == 20.0  # 4 x 10 utenti su 10 x 20
    assert out["median_ratio_survivors"] == 0.5
    assert out["by_category"]["News"]["n"] == 10
    assert az.lifecycle(history(), min_users=15, min_cat=11)["by_category"] == {}


def test_new_tail_counts_only_recent_articles():
    rows = [row("2026-11-02", i, f"N{i}", "Trailers", "2026-11-03", 5 if i < 6 else 40) for i in range(10)]
    rows += [row("2026-11-02", 100 + i, f"V{i}", "Trailers", "2026-01-01", 3) for i in range(20)]  # vecchi
    rows += [row("2026-11-02", 200 + i, f"F{i}", "Trailers", "2026-11-06", 2) for i in range(3)]  # usciti venerdi'
    t = observe.build_table(pd.DataFrame(rows), "2026-11-02")
    out = az.new_tail(t, max_age_days=14, low=10, min_n=5)
    cat = out["by_category"]["Trailers"]
    assert cat["n"] == 10 and cat["n_low"] == 6 and cat["low_pct"] == 60.0
    assert out["total"]["n"] == 10


def test_monthly_guides_ignores_missing_titles():
    rows = [row("2026-09-28", 1, "Sky ottobre 2026", "Speciali e Magazine", "2026-09-25", 75),
            row("2026-09-28", 2, None, "Speciali e Magazine", "2026-09-25", 30)]
    assert az.monthly_guides(pd.DataFrame(rows))["by_week"][0]["n"] == 1


def test_monthly_guides_per_week():
    rows = [row("2026-09-28", 1, "Sky ottobre 2026: le novità", "Speciali e Magazine", "2026-09-25", 75),
            row("2026-09-28", 2, "Prime Video ottobre 2026", "Speciali e Magazine", "2026-09-27", 64),
            row("2026-10-12", 1, "Sky ottobre 2026: le novità", "Speciali e Magazine", "2026-09-25", 6),
            row("2026-10-12", 3, "Le 6 migliori miniserie di Prime Video", "Speciali e Magazine", "2026-01-01", 45)]
    out = az.monthly_guides(pd.DataFrame(rows))
    assert out["by_week"] == [{"week_id": "2026-09-28", "n": 2, "users": 139, "median_users": 69.5},
                              {"week_id": "2026-10-12", "n": 1, "users": 6, "median_users": 6.0}]
