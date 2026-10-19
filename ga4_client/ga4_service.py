"""
ga4_service.py

Service layer GA4 in Python, corrispettivo di wp_client/ga4-service.js:
tutte le funzioni di dominio che parlano con fact_ga4_daily passano di
qui, isolando gli script di ingestion da psycopg2 e dalla logica di
matching WP.

Invarianti enforced nel codice (specchiate dal service Node):
  1. La query GA4 include SEMPRE 'date' tra le dimensions: una riga
     per giorno civile, mai un totale pre-aggregato sul periodo.
  2. Validazione riga per riga: ogni data grezza YYYYMMDD passa da
     parse_ga4_date; le righe malformate vengono scartate e loggate,
     non bloccano l'intera ingestion.
  3. La firma di scrittura e' singolare: ingest_daily_metric accetta
     una sola data. Scritture idempotenti via ON CONFLICT DO UPDATE.
  4. Il matching page_path -> article_id usa DB come single source of
     truth (articles_dim.slug), mai la risposta GA4 come cache.

Oltre alla versione singolare (ingest_daily_metric, specchio Node),
espone anche le varianti batch usate dall'ingestion per-giorno
(resolve_article_ids, to_long_format, upsert_records) perche' il
percorso Python scrive un intero giorno in un solo execute_values.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pandas as pd
from psycopg2.extras import execute_values

ALLOWED_METRICS = (
    "active_users",
    "screen_page_views",
    "sessions",
    "engaged_sessions",
    "engagement_rate",
    "bounce_rate",
    "average_session_duration",
    "user_engagement_duration",
)

GA4_METRIC_TO_COLUMN = {
    "activeUsers": "active_users",
    "screenPageViews": "screen_page_views",
    "sessions": "sessions",
    "engagedSessions": "engaged_sessions",
    "engagementRate": "engagement_rate",
    "bounceRate": "bounce_rate",
    "averageSessionDuration": "average_session_duration",
    "userEngagementDuration": "user_engagement_duration",
}

# Scrittura singolare: specchio di wp_client/ga4-service.js.
UPSERT_SQL = """
    INSERT INTO fact_ga4_daily (article_id, metric_date, metric_name, metric_value, fetched_at)
    VALUES (%s, %s, %s, %s, now())
    ON CONFLICT (article_id, metric_date, metric_name) DO UPDATE SET
        metric_value = EXCLUDED.metric_value,
        fetched_at = EXCLUDED.fetched_at
"""

# Variante batch: un intero giorno in una sola statement.
BULK_UPSERT_SQL = """
    INSERT INTO fact_ga4_daily (article_id, metric_date, metric_name, metric_value)
    VALUES %s
    ON CONFLICT (article_id, metric_date, metric_name) DO UPDATE SET
        metric_value = EXCLUDED.metric_value,
        fetched_at = now()
"""

SLUG_MAP_SQL = "SELECT slug, article_id FROM articles_dim;"


def parse_ga4_date(raw: Any) -> str | None:
    """Valida una data grezza GA4 (formato YYYYMMDD) e la restituisce
    come 'YYYY-MM-DD', oppure None se la stringa non e' una data valida.

    Round-trip sul calendario, uguale a parseGa4Date del service Node:
    scarta anche le date sintatticamente valide ma impossibili
    (es. 20260230).
    """
    if not isinstance(raw, str):
        return None
    if not re.fullmatch(r"\d{8}", raw):
        return None

    year = int(raw[0:4])
    month = int(raw[4:6])
    day = int(raw[6:8])

    if year < 1900 or year > 9999:
        return None
    if month < 1 or month > 12:
        return None
    if day < 1 or day > 31:
        return None

    try:
        parsed = dt.date(year, month, day)
    except ValueError:
        return None

    if (parsed.year, parsed.month, parsed.day) != (year, month, day):
        return None

    return parsed.isoformat()


def _clean_slug(page_path: Any) -> str:
    """Strippa query string e slash iniziali/finali da un page_path.
    Ordine importante: prima la query string, poi gli slash, come
    resolveArticleIdBySlug del service Node."""
    if not page_path:
        return ""
    without_query = str(page_path).split("?", 1)[0]
    return without_query.strip("/")


def resolve_page_path(
    page_path: Any, slug_map: dict[str, int], article_id_set: set[int]
) -> int | None:
    """Risolve un page_path GA4 in article_id.

    Il permalink di taxidrivers.it e' /<article_id>/<categoria>/<slug>.html,
    quindi il primo segmento numerico e' l'article_id stesso: se esiste in
    articles_dim e' la risoluzione piu' affidabile. I path senza prefisso
    numerico (o con id non presente) ricadono sul match esatto dell'ultimo
    segmento (senza suffisso .html) contro lo slug.

    Il match sul solo slug e' intrinsecamente ambiguo (es. uno slug che
    coincide con una pagina categoria tipo /serie-tv): per questo e' il
    fallback, non la regola principale.
    """
    clean = _clean_slug(page_path)
    if not clean:
        return None

    segments = clean.split("/")
    first = segments[0]
    if first.isdigit():
        candidate = int(first)
        if candidate in article_id_set:
            return candidate

    last = segments[-1]
    if last.endswith(".html"):
        last = last[: -len(".html")]
    return slug_map.get(last)


def resolve_article_id_by_slug(cur, page_path: Any) -> int | None:
    """Lookup di article_id dato un page_path, via match esatto sullo
    slug corrente di articles_dim. Restituisce article_id oppure None
    se non risolto.

    Specchio di resolveArticleIdBySlug del service Node. Per l'ingestion
    di massa usare resolve_page_path, che sfrutta il prefisso numerico
    del permalink ed evita i falsi positivi del solo match sullo slug.
    """
    clean_slug = _clean_slug(page_path)
    if not clean_slug:
        return None
    cur.execute(
        "SELECT article_id FROM articles_dim WHERE slug = %s LIMIT 1",
        (clean_slug,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def load_resolution_maps(cur) -> tuple[dict[str, int], set[int]]:
    """Carica da articles_dim le due strutture di risoluzione:
    slug -> article_id e l'insieme degli article_id esistenti."""
    cur.execute(SLUG_MAP_SQL)
    rows = cur.fetchall()
    slug_map = {slug: article_id for slug, article_id in rows}
    article_id_set = {article_id for _, article_id in rows}
    return slug_map, article_id_set


def resolve_article_ids(
    df: pd.DataFrame, slug_map: dict[str, int], article_id_set: set[int]
) -> tuple[pd.DataFrame, list[str]]:
    """Aggiunge article_id al df wide risolvendo page_path via prefisso
    numerico + fallback slug. Ritorna (df con sole righe matched, lista
    page_path senza match)."""
    if df.empty:
        return df, []

    df = df.copy()
    df["article_id"] = df["page_path"].map(
        lambda p: resolve_page_path(p, slug_map, article_id_set)
    )

    unmatched_mask = df["article_id"].isna()
    unmatched_paths = sorted(df.loc[unmatched_mask, "page_path"].unique().tolist())

    matched = df.loc[~unmatched_mask].copy()
    matched["article_id"] = matched["article_id"].astype(int)
    return matched, unmatched_paths


def missing_article_ids(
    unmatched_paths: list[str], article_id_set: set[int]
) -> set[int]:
    """Dai page_path non risolti estrae gli id numerici di prefisso che non
    esistono in articles_dim.

    Sono gli articoli pubblicati dopo l'ultima sincronizzazione WP (piu'
    eventuali id storici non piu' presenti come post WP): da recuperare
    con l'ingestion incrementale degli articoli prima di ri-lanciare GA4.
    """
    missing: set[int] = set()
    for path in unmatched_paths:
        clean = _clean_slug(path)
        if not clean:
            continue
        first = clean.split("/")[0]
        if first.isdigit():
            candidate = int(first)
            if candidate not in article_id_set:
                missing.add(candidate)
    return missing


def aggregate_by_article(df: pd.DataFrame) -> pd.DataFrame:
    """Collassa più page_path che risolvono allo stesso article_id nello
    stesso giorno, sommando le metriche.

    Necessario perche' la PK di fact_ga4_daily e' (article_id,
    metric_date, metric_name): senza aggregazione due URL diversi dello
    stesso articolo (es. categoria cambiata, varianti .html) generano
    righe in conflitto nella stessa statement di upsert ("ON CONFLICT
    DO UPDATE cannot affect row a second time")."""
    if df.empty:
        return df
    aggregated = df.groupby(["article_id", "event_date"], as_index=False)[
        list(ALLOWED_METRICS)
    ].sum()
    return pd.DataFrame(aggregated)


def to_long_format(df: pd.DataFrame) -> pd.DataFrame:
    """Wide (una riga per page_path/event_date, 8 colonne metriche) ->
    long (una riga per article_id/metric_date/metric_name).

    fillna(0) sui valori nulli prima della scrittura: metric_value e'
    NOT NULL, stessa scelta gia' fatta nel backfill di 0003 per le
    metriche nullable (engagement_rate, bounce_rate, *_duration).
    """
    if df.empty:
        return df

    long_df = df.melt(
        id_vars=["article_id", "event_date"],
        value_vars=list(ALLOWED_METRICS),
        var_name="metric_name",
        value_name="metric_value",
    )
    long_df["metric_value"] = long_df["metric_value"].fillna(0)
    return long_df.rename(columns={"event_date": "metric_date"})


def long_records(long_df: pd.DataFrame) -> list[tuple[int, dt.date, str, float]]:
    """Converte il df long in record python (articolo, data, metrica, valore)
    pronti per execute_values. Coerente con il tipo NUMERIC di metric_value."""
    return [
        (int(a), d, m, float(v))
        for a, d, m, v in zip(
            long_df["article_id"],
            long_df["metric_date"],
            long_df["metric_name"],
            long_df["metric_value"],
        )
    ]


def ingest_daily_metric(
    cur, article_id: Any, metric_date: Any, metric_name: Any, value: Any
) -> None:
    """Scrittura singolare e idempotente di una singola metrica giornaliera.

    Firma strettamente singolare: (article_id, date, metric_name, value).
    Niente varianti range-based, al pari del service Node.
    """
    _assert_article_id(article_id)
    _assert_date_string(metric_date)
    _assert_metric_name(metric_name)
    _assert_value(value)

    cur.execute(UPSERT_SQL, (article_id, metric_date, metric_name, value))


def upsert_records(cur, records: list[tuple[int, dt.date, str, float]]) -> None:
    """Scrive un batch di record long in fact_ga4_daily con execute_values,
    idempotente via ON CONFLICT. Si assume un unico giorno per batch."""
    if not records:
        return
    execute_values(cur, BULK_UPSERT_SQL, records)


# ---------------------------------------------------------------------------
# Validazione input (specchio degli _assert del service Node)
# ---------------------------------------------------------------------------


def _assert_article_id(article_id: Any) -> None:
    if isinstance(article_id, bool) or not isinstance(article_id, int) or article_id <= 0:
        raise ValueError(
            f"ingest_daily_metric: article_id non valido "
            f"(atteso intero positivo, ricevuto {article_id!r})."
        )


def _assert_date_string(date_str: Any) -> None:
    if not isinstance(date_str, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        raise ValueError(
            f"ingest_daily_metric: date non valida "
            f"(atteso 'YYYY-MM-DD', ricevuto {date_str!r})."
        )
    year, month, day = (int(p) for p in date_str.split("-"))
    try:
        parsed = dt.date(year, month, day)
    except ValueError as exc:
        raise ValueError(
            f"ingest_daily_metric: date '{date_str}' non valida come giorno di calendario."
        ) from exc
    if (parsed.year, parsed.month, parsed.day) != (year, month, day):
        raise ValueError(
            f"ingest_daily_metric: date '{date_str}' non valida come giorno di calendario."
        )


def _assert_metric_name(metric_name: Any) -> None:
    if metric_name not in ALLOWED_METRICS:
        raise ValueError(
            f"ingest_daily_metric: metric_name non ammesso ({metric_name!r}). "
            f"Atteso uno di: {', '.join(ALLOWED_METRICS)}."
        )


def _assert_value(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or _pandas_nan(value):
        raise ValueError(
            f"ingest_daily_metric: value non valido "
            f"(atteso valore numerico finito, ricevuto {value!r})."
        )


def _pandas_nan(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False