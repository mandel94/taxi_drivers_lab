-- Nessuna visualizzazione si perde o si duplica tra il raw e il mart per articolo.
-- (Gli articoli GA4 non presenti in articles_dim non possono esistere: c'e' la FK.)
with mart as (
    select date_day, sum(views) as mart_views
    from {{ ref('mart_article_daily') }}
    group by date_day
),
raw as (
    select date_day, sum(views) as raw_views
    from {{ ref('stg_ga4_article_daily') }}
    group by date_day
)
select
    coalesce(m.date_day, r.date_day) as date_day,
    m.mart_views,
    r.raw_views
from mart m
full join raw r on r.date_day = m.date_day
where coalesce(m.mart_views, 0) <> coalesce(r.raw_views, 0)
