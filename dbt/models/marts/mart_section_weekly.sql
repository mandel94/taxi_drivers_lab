-- Sezione primaria per settimana, DENSO: ogni sezione compare in ogni settimana coperta, anche con
-- zero. La spine deve essere densa e fermarsi all'intervallo coperto: lag(52) vale "un anno fa" solo
-- se non mancano settimane, e prima dell'inizio dei dati il confronto deve restare null, non zero.
-- views_share e' la quota sul totale delle visualizzazioni attribuite agli articoli (le quote
-- delle sezioni sommano a 1), non sul sito.
{% set metrics = ['views', 'engagement_seconds', 'articles_active'] %}

with spine as (
    select
        w.week_start_date,
        w.is_complete_week,
        s.section_key,
        s.section_name
    from {{ ref('int_week_spine') }} w
    cross join {{ ref('dim_section') }} s
    where w.scope = 'articles'
),

agg as (
    select
        week_start_date,
        section_key,
        sum(views)                              as views,
        sum(engagement_seconds)                 as engagement_seconds,
        count(*) filter (where views > 0)       as articles_active
    from {{ ref('mart_article_weekly') }}
    group by week_start_date, section_key
),

published as (
    select
        date_trunc('week', published_date::timestamp)::date as week_start_date,
        primary_section_key                                   as section_key,
        count(*)                                              as articles_published
    from {{ ref('dim_article') }}
    group by 1, 2
),

base as (
    select
        sp.week_start_date,
        sp.section_key,
        sp.section_name,
        coalesce(a.views, 0)::int                              as views,
        coalesce(a.engagement_seconds, 0)::numeric(14,2)       as engagement_seconds,
        coalesce(a.articles_active, 0)::int                    as articles_active,
        coalesce(p.articles_published, 0)::int                 as articles_published,
        sp.is_complete_week
    from spine sp
    left join agg a using (week_start_date, section_key)
    left join published p using (week_start_date, section_key)
)

select
    week_start_date,
    section_key,
    section_name,
    views,
    engagement_seconds,
    articles_active,
    articles_published,
    round(views::numeric / nullif(articles_active, 0), 2)                          as views_per_active_article,
    round(views::numeric / nullif(sum(views) over (partition by week_start_date), 0), 4) as views_share,
    is_complete_week
    {%- for m in metrics %},
    lag({{ m }}, 1)  over w as {{ m }}_prev,
    lag({{ m }}, 52) over w as {{ m }}_py
    {%- endfor %}
from base
window w as (partition by section_key order by week_start_date)
