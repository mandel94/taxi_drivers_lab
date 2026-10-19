-- Salute dei dati, una riga per fonte. E' una VISTA, non una tabella: now() viene valutato a ogni
-- lettura. Se fosse una tabella ricostruita da dbt, quando tutta la pipeline si ferma smetterebbe
-- anche di aggiornarsi e continuerebbe a dire "ok".
-- Stato: error se l'ultimo caricamento ha piu' di 72 ore o l'ultima esecuzione e' fallita;
-- warn se ha piu' di 36 ore o negli ultimi 30 giorni mancano giorni; altrimenti ok.
{{ config(materialized='view') }}

with sources as (

    select
        'ga4_articles' as source,
        max(fetched_at) as last_loaded_at,
        max(metric_date) as last_covered_date,
        {{ days_missing_last_30(source('raw', 'fact_ga4_daily'), 'metric_date', var('ga4_articles_start')) }} as days_missing_last_30
    from {{ source('raw', 'fact_ga4_daily') }}
    where metric_date >= '{{ var("ga4_articles_start") }}'::date

    union all

    select
        'ga4_site_daily',
        max(fetched_at),
        max(metric_date),
        {{ days_missing_last_30(source('raw', 'fact_ga4_site_daily'), 'metric_date', var('ga4_site_start')) }}
    from {{ source('raw', 'fact_ga4_site_daily') }}

    union all

    select
        'ga4_channel_daily',
        max(fetched_at),
        max(metric_date),
        {{ days_missing_last_30(source('raw', 'fact_ga4_channel_daily'), 'metric_date', var('ga4_site_start')) }}
    from {{ source('raw', 'fact_ga4_channel_daily') }}

    union all

    select
        'ga4_site_period',
        max(fetched_at),
        max(period_start),
        null::bigint
    from {{ source('raw', 'fact_ga4_site_period') }}

    union all

    select
        'wp_articles',
        max(updated_at),
        max(published_at)::date,
        null::bigint
    from {{ source('raw', 'articles_dim') }}

),

last_run as (
    select distinct on (source)
        source,
        status        as last_run_status,
        error_message as last_run_error
    from {{ source('raw', 'etl_run_log') }}
    where status in ('success', 'failed')
    order by source, run_id desc
),

matching as (
    -- Quota delle visualizzazioni di sito spiegata dagli articoli, sugli ultimi 30 giorni chiusi.
    select
        sum(a.views)::numeric / nullif(sum(s.page_views), 0) as matching_coverage
    from (
        select date_day, sum(views) as views
        from {{ ref('int_article_daily') }}
        group by date_day
    ) a
    join {{ ref('stg_ga4_site_daily') }} s using (date_day)
    where a.date_day between current_date - 31 and current_date - 2
),

scored as (
    select
        s.source,
        s.last_loaded_at,
        s.last_covered_date,
        s.days_missing_last_30,
        r.last_run_status,
        r.last_run_error,
        extract(epoch from (now() - s.last_loaded_at)) / 3600.0 as hours_since_load,
        case when s.source = 'ga4_articles' then round((select matching_coverage from matching), 4) end as matching_coverage
    from sources s
    left join last_run r using (source)
)

select
    source,
    last_loaded_at,
    last_covered_date,
    days_missing_last_30,
    round(hours_since_load::numeric, 1) as hours_since_load,
    last_run_status,
    matching_coverage,
    case
        when last_run_status = 'failed' or hours_since_load > 72 then 'error'
        when hours_since_load > 36 or coalesce(days_missing_last_30, 0) > 0 then 'warn'
        else 'ok'
    end as status,
    case
        when last_run_status = 'failed'
            then 'Ultima esecuzione fallita: ' || coalesce(left(last_run_error, 200), 'errore non specificato')
        when hours_since_load > 72
            then 'Dati fermi da oltre 72 ore'
        when hours_since_load > 36
            then 'Dati fermi da oltre 36 ore'
        when coalesce(days_missing_last_30, 0) > 0
            then days_missing_last_30 || ' giorni mancanti negli ultimi 30'
        else 'Dati aggiornati'
    end as status_message
from scored
