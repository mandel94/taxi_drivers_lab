"""
article_scoring.py

Score editoriale per periodo, porting della logica di td_report
(etl/content_scoring: calculator.py, weighting_strategies.py, segmentation.py)
con la configurazione usata dal report settimanale (report_config.py):

  - reach      = log(1 + activeUsers)          (metrica di ranking activeUsers)
  - engagement = engagementRate
  - depth      = averageSessionDuration
  - winsorization 5°-95° percentile su ciascuna feature
  - rank percentile (average, pct) su ciascuna feature, 0-1
  - editorial_score = (0.35 * reach + 0.35 * engagement + 0.30 * depth) * 100
  - editorial_rank  = rank(method='min', descending) sullo score
  - content_segment: quadrante reach/engagement rispetto alla mediana (rank >= 0.5)

Il calcolo opera sul dataset passato: lo score e' relativo agli articoli del periodo.
Chi chiama deve passare solo articoli (vedi article_score_job.py). Il numero di
versione del metodo vive in METHOD_VERSION e va incrementato quando cambia uno dei
punti sopra (vedi commenti della migration 0005).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


METHOD_VERSION = "balanced-v2"

# Soglia minima di inclusione sulla metrica di ranking (report_config.RANKING_THRESHOLDS).
MIN_ACTIVE_USERS = 5

WEIGHTS = {"reach": 0.35, "engagement": 0.35, "depth": 0.30}
LOWER_PERCENTILE = 0.05
UPPER_PERCENTILE = 0.95
SEGMENT_RANK_THRESHOLD = 0.5

# Metriche GA4 richieste per periodo (come WEEKLY_REPORT_METRICS in report_config.py).
GA4_METRICS = [
    "activeUsers",
    "screenPageViews",
    "engagementRate",
    "bounceRate",
    "averageSessionDuration",
    "userEngagementDuration",
    "engagedSessions",
    "sessions",
]


def _winsorize(series: pd.Series) -> pd.Series:
    lower = series.quantile(LOWER_PERCENTILE)
    upper = series.quantile(UPPER_PERCENTILE)
    return series.clip(lower, upper)


def _percentile_rank(series: pd.Series) -> pd.Series:
    if len(series) == 1:
        return pd.Series(0.5, index=series.index)
    return series.rank(method="average", pct=True)


def _segment(reach_rank: pd.Series, engagement_rank: pd.Series) -> np.ndarray:
    high_reach = reach_rank >= SEGMENT_RANK_THRESHOLD
    high_engagement = engagement_rank >= SEGMENT_RANK_THRESHOLD
    return np.select(
        [high_reach & high_engagement, high_engagement, high_reach],
        ["Champions", "Rough Diamonds", "Clickbait"],
        default="Dead Weight",
    )


def combine_pages_by_article(pages: pd.DataFrame) -> pd.DataFrame:
    """Collassa piu' pagePath che risolvono allo stesso article_id (varianti di URL).

    Le metriche additive si sommano. Le medie si ricalcolano con i pesi giusti:
    engagementRate = engagedSessions / sessions, bounceRate = 1 - engagementRate,
    averageSessionDuration = media ponderata per sessions (GA4 la definisce come
    durata totale / sessions). Input: colonna article_id e GA4_METRICS.
    """
    if pages.empty:
        return pages.assign(**{c: pd.Series(dtype=float) for c in GA4_METRICS})

    df = pages.copy()
    for col in GA4_METRICS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    df["_duration_x_sessions"] = df["averageSessionDuration"] * df["sessions"]

    grouped = df.groupby("article_id", as_index=False).agg(
        activeUsers=("activeUsers", "sum"),
        screenPageViews=("screenPageViews", "sum"),
        sessions=("sessions", "sum"),
        engagedSessions=("engagedSessions", "sum"),
        userEngagementDuration=("userEngagementDuration", "sum"),
        _duration_x_sessions=("_duration_x_sessions", "sum"),
    )
    sessions = grouped["sessions"].replace(0, np.nan)
    grouped["engagementRate"] = (grouped["engagedSessions"] / sessions).fillna(0)
    grouped["bounceRate"] = 1 - grouped["engagementRate"]
    grouped["averageSessionDuration"] = (grouped["_duration_x_sessions"] / sessions).fillna(0)
    return grouped.drop(columns=["_duration_x_sessions"])


def score_articles(df: pd.DataFrame) -> pd.DataFrame:
    """Filtra per soglia di ranking e calcola score, rank e segmento.

    Input: una riga per articolo con le colonne GA4 di GA4_METRICS (gia' aggregate
    per articolo, vedi combine_pages_by_article). Output: il DataFrame filtrato con
    feature_*, feature_*_rank, editorial_score, editorial_rank e content_segment
    aggiunti. Non modifica l'input.
    """
    missing = [c for c in GA4_METRICS if c not in df.columns]
    if missing:
        raise ValueError(f"Colonne mancanti per lo scoring: {missing}")

    out = df.copy()
    for col in GA4_METRICS:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)

    out = out[out["activeUsers"] > MIN_ACTIVE_USERS].copy()
    if out.empty:
        for col in ["feature_reach", "feature_engagement", "feature_depth",
                    "feature_reach_rank", "feature_engagement_rank", "feature_depth_rank",
                    "editorial_score", "editorial_rank", "content_segment"]:
            out[col] = pd.Series(dtype=object)
        return out

    out["feature_reach"] = np.log1p(out["activeUsers"])
    out["feature_engagement"] = out["engagementRate"]
    out["feature_depth"] = out["averageSessionDuration"]

    for feature in ["feature_reach", "feature_engagement", "feature_depth"]:
        out[feature] = _winsorize(out[feature])
        out[f"{feature}_rank"] = _percentile_rank(out[feature])

    # Arrotondato a 10 decimali: punteggi uguali nella realta' non devono dividersi
    # in rank diversi per rumore di floating point.
    out["editorial_score"] = (
        (
            WEIGHTS["reach"] * out["feature_reach_rank"]
            + WEIGHTS["engagement"] * out["feature_engagement_rank"]
            + WEIGHTS["depth"] * out["feature_depth_rank"]
        )
        * 100
    ).round(10)
    out["editorial_rank"] = (
        out["editorial_score"].rank(method="min", ascending=False).astype(int)
    )
    out["content_segment"] = _segment(out["feature_reach_rank"], out["feature_engagement_rank"])
    return out
