"""
metrics.py

Funzioni di query riusabili sulle metriche di performance degli articoli.

La fonte delle metriche e' fact_ga4_daily (formato long: una riga per
article_id, metric_date, metric_name, metric_value). Le funzioni qui
pivotano il long in wide (una colonna per metrica) e restituiscono un
DataFrame con grain articolo x giorno.

Le categorie sono trattate come attributo per-articolo (non per-giorno)
e risolte dall'helper get_article_categories: la singola fonte per
"l'ultima assegnazione fa fede" se in futuro il bridge acquisisse una
cronologia.
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable

import pandas as pd

from data_access.db import query_df

# Le 8 metriche di fact_ga4_daily, pinned dalla CHECK constraint
# chk_fact_ga4_daily_metric_name (migration 0003) e specchio di
# ga4_client.ga4_service.ALLOWED_METRICS.
GA4_METRICS = (
    "active_users",
    "screen_page_views",
    "sessions",
    "engaged_sessions",
    "engagement_rate",
    "bounce_rate",
    "average_session_duration",
    "user_engagement_duration",
)

# Colonne descrittive di articles_dim incluse sempre nel dump (leggere).
_FEATURE_COLUMNS = [
    "article_id",
    "slug",
    "link",
    "status",
    "title",
    "author_wp_id",
    "author_name",
    "featured_media_url",
    "format",
    "comment_status",
    "published_at",
    "modified_at",
]

# Colonne testuali pesanti: escluse con include_content=False.
_CONTENT_COLUMNS = ["excerpt", "content_html"]


def _metric_pivot(metric: str) -> str:
    """Espressione di pivot per una singola metrica long -> colonna wide.

    MAX() e' sicura: la PK (article_id, metric_date, metric_name) garantisce
    al piu' una riga per combinazione, quindi nessuna aggregazione reale.
    """
    return (
        f"MAX(g.metric_value) FILTER (WHERE g.metric_name = '{metric}') "
        f"AS {metric}"
    )


def _resolve_window(
    since: str | None, until: str | None, days: int
) -> tuple[dt.date, dt.date]:
    """Risolve la finestra temporale in (since, until) concreti."""
    if since and until:
        return dt.date.fromisoformat(since), dt.date.fromisoformat(until)

    end = dt.date.fromisoformat(until) if until else dt.date.today()
    if since:
        return dt.date.fromisoformat(since), end

    if days < 1:
        raise ValueError("days deve essere >= 1.")
    return end - dt.timedelta(days=days - 1), end


def _feature_select(include_content: bool) -> str:
    columns = list(_FEATURE_COLUMNS)
    if include_content:
        columns += _CONTENT_COLUMNS
    return ",\n        ".join(f"a.{c}" for c in columns)


def _feature_group_by(include_content: bool) -> str:
    columns = list(_FEATURE_COLUMNS)
    if include_content:
        columns += _CONTENT_COLUMNS
    return ",\n        ".join(f"a.{c}" for c in columns)


_PERFORMANCE_SQL = """
SELECT
    {feature_select},
    g.metric_date,
    {pivots}
FROM fact_ga4_daily g
JOIN articles_dim a ON a.article_id = g.article_id
WHERE g.metric_date BETWEEN %(since)s AND %(until)s
GROUP BY
    {feature_group_by},
    g.metric_date
ORDER BY g.metric_date, a.article_id
"""


def get_article_daily_performance(
    days: int = 90,
    since: str | None = None,
    until: str | None = None,
    include_content: bool = True,
    include_categories: bool = True,
    url: str | None = None,
) -> pd.DataFrame:
    """Articoli con performance giornaliera GA4, grain articolo x giorno.

    Restituisce una riga per combinazione (article_id, metric_date) presente
    in fact_ga4_daily nella finestra richiesta, con tutte le feature di
    articles_dim e una colonna per ciascuna delle 8 metriche GA4.

    Parametri:
      days:             finestra relativa in giorni (default 90, fino a oggi).
      since/until:      date ISO 'YYYY-MM-DD'; se fornite vincono su `days`.
      include_content:  include le colonne testuali pesanti (excerpt,
                        content_html). False per un frame piu' leggero.
      include_categories: accoda la colonna `categories` (nomi separati da
                        virgola) risolta per-articolo da get_article_categories.
      url:              DSN di override (default DATABASE_URL/.env).
    """
    since_d, until_d = _resolve_window(since, until, days)

    sql = _PERFORMANCE_SQL.format(
        feature_select=_feature_select(include_content),
        feature_group_by=_feature_group_by(include_content),
        pivots=",\n    ".join(_metric_pivot(m) for m in GA4_METRICS),
    )

    df = query_df(
        sql,
        params={"since": since_d, "until": until_d},
        url=url,
    )

    if include_categories:
        cats = get_article_categories(url=url)
        df = df.merge(cats, on="article_id", how="left")
        df["categories"] = df["categories"].fillna("")

    return df


_CATEGORIES_SQL = """
SELECT
    ac.article_id,
    COALESCE(
        STRING_AGG(DISTINCT c.name, ', ' ORDER BY c.name),
        ''
    ) AS categories
FROM articles_categories ac
JOIN categories_dim c ON c.category_id = ac.category_id
WHERE {filter}
GROUP BY ac.article_id
"""


def get_article_categories(
    article_ids: Iterable[int] | None = None,
    url: str | None = None,
) -> pd.DataFrame:
    """Categorie correnti per articolo: article_id -> 'cat1, cat2, ...'.

    L'assegnazione corrente di articles_categories (gia' l'ultima dopo ogni
    sync WP) fa fede. Se in futuro il bridge acquisisse una cronologia,
    questa e' l'unica funzione da modificare per codificare "l'ultima
    assegnazione fa fede" (es. ordinando per timestamp).

    Parametri:
      article_ids:  se fornito, limita il risultato a questi article_id.
      url:          DSN di override.
    """
    ids = list(article_ids) if article_ids is not None else None

    if ids:
        filter_clause = "ac.article_id = ANY(%(ids)s)"
        params = {"ids": ids}
    else:
        filter_clause = "TRUE"
        params = {}

    sql = _CATEGORIES_SQL.format(filter=filter_clause)
    return query_df(sql, params=params, url=url)
