-- Articolo per settimana (lunedi), SPARSO. comment_count e was_modified_in_week non ci sono:
-- fact_wp_engagement_weekly e' vuota e nessuno script la popola.
-- La fascia di eta' e' quella al lunedi della settimana (minimo 0).
with weekly as (
    select
        week_start_date,
        article_id,
        title,
        link,
        section_key,
        section_name,
        count(distinct date_day) filter (where views > 0)  as active_days,
        sum(views)::int                                      as views,
        sum(engagement_seconds)::numeric(14,2)               as engagement_seconds,
        sum(sessions_attributed)::int                        as sessions_attributed,
        sum(engaged_sessions_attributed)::int                as engaged_sessions_attributed
    from {{ ref('int_article_daily') }}
    group by week_start_date, article_id, title, link, section_key, section_name
)

select
    w.week_start_date,
    w.article_id,
    w.title,
    w.link,
    w.section_key,
    w.section_name,
    {{ age_bucket('greatest(0, w.week_start_date - a.published_date)') }}                           as age_bucket,
    greatest(0, (w.week_start_date - date_trunc('week', a.published_date::timestamp)::date) / 7)  as weeks_since_publication,
    w.active_days,
    w.views,
    w.engagement_seconds,
    w.sessions_attributed,
    w.engaged_sessions_attributed,
    sp.is_complete_week
from weekly w
join {{ ref('dim_article') }} a on a.article_id = w.article_id
join {{ ref('int_week_spine') }} sp
    on sp.scope = 'articles' and sp.week_start_date = w.week_start_date
