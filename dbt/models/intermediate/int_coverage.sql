-- Intervallo di copertura dei dati GA4. L'inizio e' esplicito (variabili di progetto),
-- la fine e' l'ultimo giorno caricato. I mart usano questo intervallo come spine: i giorni
-- prima dell'inizio non esistono, quindi i confronti con l'anno prima restano null invece
-- di mostrare zeri veri.
select
    'articles' as scope,
    '{{ var("ga4_articles_start") }}'::date as start_date,
    (select max(date_day) from {{ ref('stg_ga4_article_daily') }}) as end_date

union all

select
    'site' as scope,
    '{{ var("ga4_site_start") }}'::date as start_date,
    (select max(date_day) from {{ ref('stg_ga4_site_daily') }}) as end_date
