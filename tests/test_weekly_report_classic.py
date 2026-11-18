import datetime as dt
import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ga4_client"))

from weekly_report_classic import (  # noqa: E402
    arrow, build, category_er, clean_set, ddmmyy, pick_cluster, split_exclusions,
)

START, END = dt.date(2026, 11, 9), dt.date(2026, 11, 15)


def _r(title, cat, users, er=0.6, dur=80, pub="2026-11-10", views=None, path=None, author="Aut"):
    return {"title": title, "author": author, "category": cat, "pagePath": path or f"/{abs(hash(title)) % 99999}/",
            "users": users, "views": views if views is not None else users, "er": er, "dur": dur,
            "pub": pd.Timestamp(pub), "bounce": 1 - er, "anomaly": False}


def test_pick_cluster_keeps_ties_together_and_caps_at_six():
    assert pick_cluster([50, 49, 48, 47, 46, 45, 44, 43]) == 6
    assert pick_cluster([50, 30, 20, 10, 5]) == 3
    # il pari merito sul quarto posto non va spezzato: si ferma prima del gruppo
    assert pick_cluster([50, 49, 48, 20, 20, 20]) == 3


def test_clean_set_filters():
    df = pd.DataFrame([
        _r("ok", "News", 10), _r("er basso", "News", 10, er=0.2), _r("durata breve", "News", 10, dur=3),
        _r("", "News", 10), _r("zero", "News", 10, er=0.0),
    ])
    assert list(clean_set(df)["title"]) == ["ok"]


def test_permanent_exclusions_by_title_and_path():
    df = pd.DataFrame([
        _r("5 attrici famose che facevano le pornostar", "News", 99), _r("Altro", "News", 5, path="/x/altadefinizione/"),
        _r("Vero", "News", 7),
    ])
    keep, out = split_exclusions(df)
    assert list(keep["title"]) == ["Vero"] and len(out) == 2


def test_category_er_is_weighted_by_users_and_needs_three_articles():
    df = pd.DataFrame([_r("a", "Serie TV", 90, er=0.9), _r("b", "Serie TV", 10, er=0.1), _r("c", "Serie TV", 10, er=0.1),
                       _r("d", "News", 50, er=0.5), _r("e", "News", 50, er=0.5)])
    er = category_er(df)
    assert "News" not in er.index
    assert round(er["Serie TV"], 1) == round((0.9 * 90 + 0.1 * 10 + 0.1 * 10) / 110 * 100, 1)


def test_arrow_and_header_format():
    assert arrow(30, 20) == "_(↑)_" and arrow(10, 20) == "_(↓)_" and arrow(20, 20.2) == "_(=)_" and arrow(20, None) == "_(—)_"
    assert ddmmyy(START) == "091126"


def test_build_report_structure_trailers_window_and_notes():
    rows = [_r(f"Serie {i}", "Serie TV", 40 - i) for i in range(4)]
    rows += [_r("Trailer nuovo", "Trailers", 30, pub="2026-11-12"), _r("Trailer vecchio", "Trailers", 29, pub="2026-09-01")]
    text, data = build(pd.DataFrame(rows), START, END, None, "(esclusi il 10 e l'11)")
    assert text.startswith("*📊 Report Settimanale*\n*091126 – 151126*")
    assert "*📺 Serie TV*" in text and "{{ANALISI}}" in text
    tr = text.split("*TOP TRAILERS*")[1].split("---")[0]
    assert "Trailer nuovo" in tr and "Trailer vecchio" not in tr
    assert "NOTE PER MANUEL" in text and "(esclusi il 10 e l'11)" in text
    assert data["users_sum"] == sum(r["users"] for r in rows)
