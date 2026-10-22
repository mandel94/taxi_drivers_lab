"""
tests/test_article_score_writer.py

Test delle funzioni pure di ga4_client/article_score_writer.py: costruzione delle
righe e validazioni. Nessun database.

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
)


PERIOD = (dt.date(2026, 10, 12), dt.date(2026, 10, 18))


def _scored(**overrides):
    base = {
        "article_id": 42,
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


def test_build_rows_maps_columns_in_fact_order():
    rows = build_rows(_scored(), *PERIOD, "balanced-v2")

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


def test_build_rows_converts_nan_to_none():
    rows = build_rows(_scored(engagementRate=float("nan")), *PERIOD, "balanced-v2")
    row = dict(zip(FACT_COLUMNS, rows[0]))
    assert row["engagement_rate"] is None


def test_build_rows_rejects_duplicate_article():
    df = pd.concat([_scored(), _scored()])
    with pytest.raises(ValueError, match="article_id duplicati"):
        build_rows(df, *PERIOD, "balanced-v2")


def test_build_rows_rejects_unknown_segment():
    with pytest.raises(ValueError, match="Segmenti fuori vocabolario"):
        build_rows(_scored(content_segment="Standard"), *PERIOD, "balanced-v2")


def test_build_rows_rejects_missing_columns():
    with pytest.raises(ValueError, match="Colonne mancanti"):
        build_rows(_scored().drop(columns=["editorial_score"]), *PERIOD, "balanced-v2")


@pytest.mark.parametrize("version", ["balanced-v2", "quality-v10", "deep-dive-v1"])
def test_method_version_accepts_convention(version):
    assert METHOD_VERSION_RE.match(version)


@pytest.mark.parametrize("version", ["balanced", "v2", "Balanced-v2", "balanced-2"])
def test_method_version_rejects_other_formats(version):
    assert not METHOD_VERSION_RE.match(version)
