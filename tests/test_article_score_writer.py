"""
tests/test_article_score_writer.py

Test delle funzioni pure di ga4_client/article_score_writer.py: normalizzazione
del path, costruzione delle righe, validazioni. Nessun database.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_article_score_writer.py
"""

import datetime as dt
import pathlib
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ga4_client"))

from article_score_writer import (  # noqa: E402
    COLUMN_MAP,
    FACT_COLUMNS,
    METHOD_VERSION_RE,
    build_rows,
    clean_page_path,
)


PERIOD = (dt.date(2026, 10, 19), dt.date(2026, 10, 22))


def _scored(**overrides):
    base = {
        "pagePath": "/560495/latest-news/si-fara/slow-horses-7.html",
        "activeUsers": 276,
        "screenPageViews": 301,
        "sessions": 276,
        "engagedSessions": 222,
        "engagementRate": 0.7735,
        "bounceRate": 0.2265,
        "averageSessionDuration": 92.77,
        "userEngagementDuration": 16252,
        "feature_reach_rank": 0.974,
        "feature_engagement_rank": 0.831,
        "feature_depth_rank": 0.626,
        "editorial_score": 81.95,
        "editorial_rank": 6,
        "content_segment": "Champions",
    }
    base.update(overrides)
    return pd.DataFrame([base])


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("/560495/a/b.html", "560495/a/b.html"),
        ("560495/a/b.html/", "560495/a/b.html"),
        ("/a/b/?utm_source=x", "a/b"),
        ("/", None),
        ("", None),
        (None, None),
        (float("nan"), None),
    ],
)
def test_clean_page_path(raw, expected):
    assert clean_page_path(raw) == expected


def test_build_rows_maps_columns_in_fact_order():
    slug = clean_page_path("/560495/latest-news/si-fara/slow-horses-7.html")
    rows, unmatched = build_rows(_scored(), *PERIOD, "balanced-v2", {slug: 42})

    assert unmatched == []
    assert len(rows) == 1
    row = dict(zip(FACT_COLUMNS, rows[0]))
    assert row["article_id"] == 42
    assert row["period_start"] == PERIOD[0]
    assert row["period_end"] == PERIOD[1]
    assert row["method_version"] == "balanced-v2"
    assert row["reach_rank"] == pytest.approx(0.974)
    assert row["editorial_score"] == pytest.approx(81.95)
    assert row["content_segment"] == "Champions"
    assert set(COLUMN_MAP.values()) <= set(row)


def test_build_rows_reports_unmatched_paths():
    rows, unmatched = build_rows(_scored(), *PERIOD, "balanced-v2", {})
    assert rows == []
    assert unmatched == ["/560495/latest-news/si-fara/slow-horses-7.html"]


def test_build_rows_converts_nan_to_none():
    slug = clean_page_path("/560495/latest-news/si-fara/slow-horses-7.html")
    rows, _ = build_rows(_scored(engagementRate=float("nan")), *PERIOD, "balanced-v2", {slug: 42})
    row = dict(zip(FACT_COLUMNS, rows[0]))
    assert row["engagement_rate"] is None


def test_build_rows_rejects_duplicate_article_after_resolution():
    df = pd.concat([_scored(), _scored(pagePath="/560495/latest-news/si-fara/slow-horses-7.html/")])
    slug = clean_page_path("/560495/latest-news/si-fara/slow-horses-7.html")
    with pytest.raises(ValueError, match="compare piu' volte"):
        build_rows(df, *PERIOD, "balanced-v2", {slug: 42})


def test_build_rows_rejects_unknown_segment():
    slug = clean_page_path("/560495/latest-news/si-fara/slow-horses-7.html")
    with pytest.raises(ValueError, match="Segmenti fuori vocabolario"):
        build_rows(_scored(content_segment="Standard"), *PERIOD, "balanced-v2", {slug: 42})


def test_build_rows_rejects_missing_columns():
    with pytest.raises(ValueError, match="Colonne mancanti"):
        build_rows(_scored().drop(columns=["editorial_score"]), *PERIOD, "balanced-v2", {})


@pytest.mark.parametrize("version", ["balanced-v2", "quality-v10", "deep-dive-v1"])
def test_method_version_accepts_convention(version):
    assert METHOD_VERSION_RE.match(version)


@pytest.mark.parametrize("version", ["balanced", "v2", "Balanced-v2", "balanced-2"])
def test_method_version_rejects_other_formats(version):
    assert not METHOD_VERSION_RE.match(version)
