"""
article_score_writer.py

Scrittura di fact_article_score_period (migration 0005): score editoriale,
rank percentili, segmento e input GA4 di ogni articolo per un periodo, con il
tag del metodo di calcolo.

Lo score e' calcolato a monte (article_scoring.py) sul dataset del periodo.
Questo modulo riceve righe gia' risolte su article_id (la risoluzione dei
pagePath sta in article_score_job.py) e fa un upsert idempotente.

Un article_id che compare due volte nello stesso periodo e' un errore: l'upsert
non puo' toccare la stessa riga due volte. Il chiamante aggrega prima.
"""

from __future__ import annotations

import datetime as dt
import re

import pandas as pd
from psycopg2.extras import execute_values

from etl_log import finish_run, start_run


SOURCE = "article_score_period"

# Colonna del DataFrame scorato -> colonna della fact table.
COLUMN_MAP = {
    "activeUsers": "active_users",
    "screenPageViews": "screen_page_views",
    "sessions": "sessions",
    "engagedSessions": "engaged_sessions",
    "engagementRate": "engagement_rate",
    "bounceRate": "bounce_rate",
    "averageSessionDuration": "average_session_duration",
    "userEngagementDuration": "user_engagement_duration",
    "feature_reach_rank": "reach_rank",
    "feature_engagement_rank": "engagement_rank",
    "feature_depth_rank": "depth_rank",
    "editorial_score": "editorial_score",
    "editorial_rank": "editorial_rank",
    "content_segment": "content_segment",
}

FACT_COLUMNS = [
    "article_id",
    "period_start",
    "period_end",
    "method_version",
    *COLUMN_MAP.values(),
]

# '<strategia>-v<N>', es. 'balanced-v2'. Vedi commenti della migration 0005.
METHOD_VERSION_RE = re.compile(r"^[a-z][a-z0-9-]*-v\d+$")

SEGMENTS = {"Champions", "Rough Diamonds", "Clickbait", "Dead Weight"}

KEY_COLUMNS = ("article_id", "period_start", "period_end", "method_version")
UPDATE_COLUMNS = [c for c in FACT_COLUMNS if c not in KEY_COLUMNS]

UPSERT_SQL = (
    "INSERT INTO fact_article_score_period (" + ", ".join(FACT_COLUMNS) + ") VALUES %s "
    "ON CONFLICT (" + ", ".join(KEY_COLUMNS) + ") DO UPDATE SET "
    + ", ".join(f"{c} = EXCLUDED.{c}" for c in UPDATE_COLUMNS)
    + ", computed_at = now()"
)


def build_rows(
    scored: pd.DataFrame,
    period_start: dt.date,
    period_end: dt.date,
    method_version: str,
) -> list[tuple]:
    """Trasforma il DataFrame scorato (con article_id) in tuple per la fact table.

    Solleva ValueError se mancano colonne, se un article_id compare due volte o se
    lo scoring contiene segmenti fuori vocabolario.
    """
    missing = [c for c in ["article_id", *COLUMN_MAP] if c not in scored.columns]
    if missing:
        raise ValueError(f"Colonne mancanti nel DataFrame scorato: {missing}")

    unknown_segments = set(scored["content_segment"]) - SEGMENTS
    if unknown_segments:
        raise ValueError(f"Segmenti fuori vocabolario: {sorted(unknown_segments)}")

    duplicated = scored["article_id"][scored["article_id"].duplicated()].unique()
    if len(duplicated):
        raise ValueError(
            f"article_id duplicati nel periodo {period_start}..{period_end}: "
            f"{sorted(int(a) for a in duplicated)[:10]}"
        )

    rows = []
    for _, record in scored.iterrows():
        values = [_py(record[src]) for src in COLUMN_MAP]
        rows.append((int(record["article_id"]), period_start, period_end, method_version, *values))
    return rows


def _py(value):
    """numpy/pandas -> tipi Python per psycopg2; NaN -> NULL."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def upsert_article_scores(cur, rows) -> int:
    """Upsert idempotente: rilanciare lo stesso periodo e versione aggiorna le righe."""
    if rows:
        execute_values(cur, UPSERT_SQL, rows)
    return len(rows)


def write_article_scores(
    conn,
    scored: pd.DataFrame,
    period_start: dt.date,
    period_end: dt.date,
    method_version: str,
) -> dict:
    """Scrive un periodo scorato con log in etl_run_log.

    Ritorna {'written': n}. In caso di errore fa rollback, registra 'failed'
    nel log e rilancia l'eccezione.
    """
    if period_end < period_start:
        raise ValueError(f"period_end {period_end} precede period_start {period_start}")
    if not METHOD_VERSION_RE.match(method_version):
        raise ValueError(f"method_version non valido: {method_version!r} (atteso '<strategia>-v<N>')")

    run_id = start_run(conn, SOURCE, period_start, period_end)
    try:
        rows = build_rows(scored, period_start, period_end, method_version)
        with conn.cursor() as cur:
            written = upsert_article_scores(cur, rows)
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - qualunque errore va loggato e rilanciato
        conn.rollback()
        finish_run(conn, run_id, "failed", None, f"{type(exc).__name__}: {exc}")
        raise

    finish_run(conn, run_id, "success", written)
    print(f"[{SOURCE}] {period_start}..{period_end} {method_version}: scritti {written}")
    return {"written": written}
