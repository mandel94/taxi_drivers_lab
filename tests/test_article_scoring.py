"""
tests/test_article_scoring.py

Regressione di ga4_client/article_scoring.py contro il report settimanale.

La fixture tests/fixtures/weekly_report_sample.csv contiene 195 articoli del
top_articles_by_category della settimana 19-22 ottobre 2026 (copia di sola lettura):
input GA4, score e rank calcolati da td_report, segmento calcolato con la logica
a quadranti di td_report/etl/content_scoring/segmentation.py.

Il porting deve riprodurre quei valori. Un solo pareggio puo' differire di un rank:
td_report spezza il pareggio con il rumore di floating point, il porting no.

Esecuzione (dalla root del repo):
    python -m pytest tests/test_article_scoring.py
"""

import pathlib
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ga4_client"))

from article_scoring import MIN_ACTIVE_USERS, METHOD_VERSION, score_articles  # noqa: E402

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "weekly_report_sample.csv"


@pytest.fixture(scope="module")
def weekly():
    return pd.read_csv(FIXTURE)


@pytest.fixture(scope="module")
def scored(weekly):
    return score_articles(weekly)


def test_method_version_is_balanced_v2():
    assert METHOD_VERSION == "balanced-v2"


def test_score_matches_weekly_report(weekly, scored):
    diff = np.abs(scored["editorial_score"].to_numpy() - weekly["editorial_score"].to_numpy())
    assert diff.max() < 1e-6


def test_feature_ranks_match_weekly_report(weekly, scored):
    for col in ["feature_reach_rank", "feature_engagement_rank", "feature_depth_rank"]:
        assert np.abs(scored[col].to_numpy() - weekly[col].to_numpy()).max() < 1e-9


def test_editorial_rank_matches_weekly_report_except_float_ties(weekly, scored):
    # Un pareggio nel riferimento (td_report) puo' essere spezzato diversamente.
    mismatches = int((scored["editorial_rank"].to_numpy() != weekly["editorial_rank"].to_numpy()).sum())
    assert mismatches <= 1


def test_segments_match_quadrant_logic(weekly, scored):
    assert (scored["content_segment"].to_numpy() == weekly["expected_segment"].to_numpy()).all()


def test_excludes_articles_at_or_below_threshold(weekly):
    low = weekly.iloc[:3].copy()
    low["activeUsers"] = MIN_ACTIVE_USERS
    rest = weekly.iloc[3:]
    out = score_articles(pd.concat([low, rest]))
    assert len(out) == len(rest)


def test_score_range_and_rank_bounds(scored):
    assert scored["editorial_score"].between(0, 100).all()
    assert scored["editorial_rank"].min() == 1
    assert scored["editorial_rank"].max() <= len(scored)


def test_empty_input_returns_empty_with_columns(weekly):
    out = score_articles(weekly.iloc[0:0])
    assert out.empty
    assert {"editorial_score", "editorial_rank", "content_segment"} <= set(out.columns)


def test_missing_column_is_explicit(weekly):
    with pytest.raises(ValueError, match="Colonne mancanti"):
        score_articles(weekly.drop(columns=["engagementRate"]))


def test_input_is_not_modified(weekly):
    before = weekly.copy()
    score_articles(weekly)
    pd.testing.assert_frame_equal(weekly, before)


def test_combine_pages_sums_and_recomputes_ratios():
    from article_scoring import combine_pages_by_article

    pages = pd.DataFrame(
        {
            "article_id": [7, 7, 8],
            "pagePath": ["/7/a.html", "/7/cat/a.html", "/8/b.html"],
            "activeUsers": [10, 5, 3],
            "screenPageViews": [20, 5, 4],
            "sessions": [10, 10, 2],
            "engagedSessions": [6, 4, 1],
            "engagementRate": [0.6, 0.4, 0.5],
            "bounceRate": [0.4, 0.6, 0.5],
            "averageSessionDuration": [100.0, 50.0, 30.0],
            "userEngagementDuration": [600, 200, 30],
        }
    )
    out = combine_pages_by_article(pages).set_index("article_id")

    assert len(out) == 2
    a7 = out.loc[7]
    assert a7["activeUsers"] == 15
    assert a7["sessions"] == 20
    assert a7["engagedSessions"] == 10
    assert a7["engagementRate"] == pytest.approx(0.5)
    assert a7["bounceRate"] == pytest.approx(0.5)
    # media ponderata per sessions: (100*10 + 50*10) / 20
    assert a7["averageSessionDuration"] == pytest.approx(75.0)
    assert out.loc[8]["averageSessionDuration"] == pytest.approx(30.0)
