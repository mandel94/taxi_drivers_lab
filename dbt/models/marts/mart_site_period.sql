-- Totali di sito per settimana (lunedi-domenica) o mese. Qui il periodo e' l'unita', quindi
-- _prev (periodo precedente dello stesso tipo) e _py (52 settimane o 12 mesi prima) sono esatti.
-- active_users e new_users sono gli utenti UNICI del periodo letti da GA4 (non sommati dai
-- giornalieri); le altre metriche sono sommate dai giornalieri del periodo.
-- Il periodo in corso ha is_complete = false.
{% set metrics = ['active_users', 'new_users', 'sessions', 'engaged_sessions', 'page_views',
                  'engagement_seconds', 'engagement_rate', 'engagement_seconds_per_user'] %}

with period_sums as (
    select
        p.period_type,
        p.period_start,
        sum(d.sessions)             as sessions,
        sum(d.engaged_sessions)     as engaged_sessions,
        sum(d.page_views)           as page_views,
        sum(d.engagement_seconds)   as engagement_seconds
    from {{ ref('stg_ga4_site_period') }} p
    join {{ ref('stg_ga4_site_daily') }} d
        on d.date_day between p.period_start and p.period_end
    group by p.period_type, p.period_start
),

base as (
    select
        p.period_type,
        p.period_start,
        p.period_end,
        p.is_complete,
        p.active_users,
        p.new_users,
        coalesce(s.sessions, 0)::int                        as sessions,
        coalesce(s.engaged_sessions, 0)::int                as engaged_sessions,
        coalesce(s.page_views, 0)::int                      as page_views,
        coalesce(s.engagement_seconds, 0)::numeric(14,2)    as engagement_seconds
    from {{ ref('stg_ga4_site_period') }} p
    left join period_sums s using (period_type, period_start)
),

rated as (
    select
        *,
        round(engaged_sessions::numeric / nullif(sessions, 0), 4)   as engagement_rate,
        round(engagement_seconds / nullif(active_users, 0), 2)      as engagement_seconds_per_user
    from base
)

select
    period_type,
    period_start,
    period_end,
    is_complete
    {%- for m in metrics %},
    {{ m }}
    {%- endfor %}
    {%- for m in metrics %},
    lag({{ m }}, 1) over w as {{ m }}_prev,
    lag({{ m }}, case when period_type = 'week' then 52 else 12 end) over w as {{ m }}_py
    {%- endfor %}
from rated
window w as (partition by period_type order by period_start)
