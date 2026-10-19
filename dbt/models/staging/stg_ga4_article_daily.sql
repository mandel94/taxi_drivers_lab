-- Dalla fact long (una riga per metrica) a una riga per articolo e giorno.
-- La PK (article_id, metric_date, metric_name) garantisce un solo valore per metrica,
-- quindi sum(...) filter(...) equivale a "prendi quel valore"; l'assenza vale zero per le
-- metriche additive. Non si porta avanti nessun rapporto (engagement_rate, bounce_rate,
-- average_session_duration): si ricalcolano dai componenti nei mart.
-- Solo da ga4_articles_start: nel DB ci sono giorni isolati caricati per prova, fuori
-- dalla finestra di copertura continua.
select
    article_id,
    metric_date as date_day,
    coalesce(sum(metric_value) filter (where metric_name = 'screen_page_views'), 0)::int            as views,
    coalesce(sum(metric_value) filter (where metric_name = 'user_engagement_duration'), 0)::numeric(14,2) as engagement_seconds,
    coalesce(sum(metric_value) filter (where metric_name = 'sessions'), 0)::int                      as sessions_attributed,
    coalesce(sum(metric_value) filter (where metric_name = 'engaged_sessions'), 0)::int              as engaged_sessions_attributed
from {{ source('raw', 'fact_ga4_daily') }}
where metric_date >= '{{ var("ga4_articles_start") }}'::date
group by article_id, metric_date
