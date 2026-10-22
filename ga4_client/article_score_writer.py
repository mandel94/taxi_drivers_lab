"""
article_score_writer.py

Scrittura di fact_article_score_period (migration 0005): score editoriale,
rank percentili, segmento e input GA4 di ogni articolo per un periodo, con il
tag del metodo di calcolo.

Lo score e' calcolato a monte (td_report, etl/content_scoring) sul dataset del
periodo. Questo modulo non ricalcola nulla: prende il DataFrame gia' scorato,
risolve pagePath -> article_id con la stessa regola di wp_client/ga4-service.js
(query string tolta, slash iniziali/finali tolti, match esatto su articles_dim.slug)
e fa un upsert idempotente.

Gli articoli il cui path non si risolve non vengono scritti: vengono restituiti
in `unmatched` e il log del job riporta quanti sono, cosi' nessuno sparisce in
silenzio.
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
PAGE_PATH_COLUMN = "pagePath"

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


def clean_page_path(page_path) -> str | None:
    """Stessa regola di resolveArticleIdBySlug in wp_client/ga4-service.js."""
    if page_path is None or (isinstance(page_path, float) and pd.isna(page_path)):
        return None
    without_query = str(page_path).split("?")[0]
    slug = re.sub(r"^/+|/+$", "", without_query)
    return slug or None


def resolve_article_ids(cur, page_paths) -> dict[str, int]:
    """Mappa slug -> article_id per i path dati. Path non risolti non compaiono."""
    slugs = sorted({s for s in (clean_page_path(p) for p in page_paths) if s})
    if not slugs:
        return {}
    cur.execute(
        "SELECT slug, article_id FROM articles_dim WHERE slug = ANY(%s)",
        (slugs,),
    )
    return {slug: article_id for slug, article_id in cur.fetchall()}


def build_rows(
    scored: pd.DataFrame,
    period_start: dt.date,
    period_end: dt.date,
    method_version: str,
    slug_to_id: dict[str, int],
) -> tuple[list[tuple], list[str]]:
    """Trasforma il DataFrame scorato in tuple per la fact table.

    Ritorna (rows, unmatched): unmatched elenca i pagePath non risolti.
    Solleva ValueError se mancano colonne, se un article_id compare due volte
    (l'upsert non puo' toccare la stessa riga due volte) o se un valore viola il
    dominio, cosi' il problema e' chiaro prima del DB.
    """
    missing = [c for c in [PAGE_PATH_COLUMN, *COLUMN_MAP] if c not in scored.columns]
    if missing:
        raise ValueError(f"Colonne mancanti nel DataFrame scorato: {missing}")

    unknown_segments = set(scored["content_segment"]) - SEGMENTS
    if unknown_segments:
        raise ValueError(f"Segmenti fuori vocabolario: {sorted(unknown_segments)}")

    rows: list[tuple] = []
    unmatched: list[str] = []
    seen: set[int] = set()

    for _, record in scored.iterrows():
        slug = clean_page_path(record[PAGE_PATH_COLUMN])
        article_id = slug_to_id.get(slug) if slug else None
        if article_id is None:
            unmatched.append(str(record[PAGE_PATH_COLUMN]))
            continue
        if article_id in seen:
            raise ValueError(
                f"article_id {article_id} compare piu' volte nel periodo "
                f"{period_start}..{period_end}: stesso slug da path diversi"
            )
        seen.add(article_id)

        values = [_py(record[src]) for src in COLUMN_MAP]
        rows.append((article_id, period_start, period_end, method_version, *values))

    return rows, unmatched


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

    Ritorna {'written': n, 'unmatched': [...]}. In caso di errore fa rollback,
    registra 'failed' nel log e rilancia l'eccezione.
    """
    if period_end < period_start:
        raise ValueError(f"period_end {period_end} precede period_start {period_start}")
    if not METHOD_VERSION_RE.match(method_version):
        raise ValueError(f"method_version non valido: {method_version!r} (atteso '<strategia>-v<N>')")

    run_id = start_run(conn, SOURCE, period_start, period_end)
    try:
        with conn.cursor() as cur:
            slug_to_id = resolve_article_ids(cur, scored[PAGE_PATH_COLUMN])
            rows, unmatched = build_rows(scored, period_start, period_end, method_version, slug_to_id)
            written = upsert_article_scores(cur, rows)
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - qualunque errore va loggato e rilanciato
        conn.rollback()
        finish_run(conn, run_id, "failed", None, f"{type(exc).__name__}: {exc}")
        raise

    finish_run(conn, run_id, "success", written)
    print(
        f"[{SOURCE}] {period_start}..{period_end} {method_version}: "
        f"scritti {written}, non risolti {len(unmatched)}"
    )
    return {"written": written, "unmatched": unmatched}
