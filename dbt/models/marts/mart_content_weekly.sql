-- Intero sito (solo articoli) per settimana, DENSO. Articoli nuovi = meno di 30 giorni alla data
-- della metrica (is_new_30d), archivio = il resto. top10_share = visualizzazioni dei 10 articoli
-- piu' letti della settimana sul totale.
{% set metrics = ['views_total', 'views_new_30d', 'views_archive'] %}

with weekly_article as (
    select
        week_start_date,
        article_id,
        sum(views) as views
    from {{ ref('int_article_daily') }}
    group by week_start_date, article_id
),

ranked as (
    select
        week_start_date,
        views,
        row_number() over (partition by week_start_date order by views desc, article_id) as rn
    from weekly_article
),

totals as (
    select
        week_start_date,
        sum(views)                              as views_total,
        count(*) filter (where views > 0)       as articles_active,
        sum(views) filter (where rn <= 10)      as top10_views
    from ranked
    group by week_start_date
),

new_vs_archive as (
    select
        week_start_date,
        sum(views) filter (where is_new_30d)        as views_new_30d,
        sum(views) filter (where not is_new_30d)    as views_archive
    from {{ ref('int_article_daily') }}
    group by week_start_date
),

base as (
    select
        sp.week_start_date,
        coalesce(t.views_total, 0)::int       as views_total,
        coalesce(n.views_new_30d, 0)::int     as views_new_30d,
        coalesce(n.views_archive, 0)::int     as views_archive,
        coalesce(t.articles_active, 0)::int   as articles_active,
        coalesce(t.top10_views, 0)::int       as top10_views,
        sp.is_complete_week
    from {{ ref('int_week_spine') }} sp
    left join totals t using (week_start_date)
    left join new_vs_archive n using (week_start_date)
    where sp.scope = 'articles'
)

select
    week_start_date,
    views_total,
    views_new_30d,
    views_archive,
    round(views_new_30d::numeric / nullif(views_total, 0), 4)  as share_new,
    round(top10_views::numeric / nullif(views_total, 0), 4)    as top10_share,
    articles_active,
    is_complete_week
    {%- for m in metrics %},
    lag({{ m }}, 1)  over w as {{ m }}_prev,
    lag({{ m }}, 52) over w as {{ m }}_py
    {%- endfor %}
from base
window w as (order by week_start_date)
