-- Totali di sito per giorno, DENSO: un giorno senza riga in GA4 vale zero per i componenti
-- additivi (un buco della pipeline lo segnala mart_data_health, non questo mart).
-- Regole di metrica:
--  * i rapporti si ricalcolano dai componenti, mai si salvano; denominatore zero = null.
--  * la media mobile di un rapporto e' il rapporto delle somme su 7 giorni, non la media dei
--    rapporti giornalieri: lunedi 100 sessioni al 50%, martedi 10 al 100% fanno 60/110 = 54,5%
--    e non 75%. I giorni piccoli non devono pesare quanto i grandi.
--  * i confronti sono a spostamento fisso (_p7 = 7 giorni prima, _py = 364 giorni prima, stesso
--    giorno della settimana) e funzionano perche' la spine e' densa. Prima dell'inizio della
--    copertura restano null.
--  * active_users non si somma tra giorni: _ma7 e' "utenti attivi medi al giorno".
{% set lagged = ['active_users', 'new_users', 'sessions', 'page_views', 'engagement_seconds', 'engagement_rate'] %}

with cov as (
    select start_date, end_date from {{ ref('int_coverage') }} where scope = 'site'
),

spine as (
    select d.date_day, d.week_start_date
    from {{ ref('dim_date') }} d
    join cov on d.date_day between cov.start_date and cov.end_date
),

articles as (
    select date_day, sum(views)::int as articles_views
    from {{ ref('int_article_daily') }}
    group by date_day
),

daily as (
    select
        sp.date_day,
        sp.week_start_date,
        coalesce(s.active_users, 0)                          as active_users,
        coalesce(s.new_users, 0)                             as new_users,
        coalesce(s.sessions, 0)                              as sessions,
        coalesce(s.engaged_sessions, 0)                      as engaged_sessions,
        coalesce(s.page_views, 0)                            as page_views,
        coalesce(s.engagement_seconds, 0)::numeric(14,2)     as engagement_seconds,
        a.articles_views,
        row_number() over (order by sp.date_day)             as rn
    from spine sp
    left join {{ ref('stg_ga4_site_daily') }} s using (date_day)
    left join articles a using (date_day)
),

rated as (
    select
        *,
        round(engaged_sessions::numeric / nullif(sessions, 0), 4)              as engagement_rate,
        round(engagement_seconds / nullif(active_users, 0), 2)                 as engagement_seconds_per_user,
        round(articles_views::numeric / nullif(page_views, 0), 4)              as matching_coverage
    from daily
)

select
    date_day,
    week_start_date,
    active_users,
    new_users,
    sessions,
    engaged_sessions,
    page_views,
    engagement_seconds,
    engagement_rate,
    engagement_seconds_per_user,
    date_day >= current_date - {{ var('provisional_days') }} as is_provisional,
    articles_views,
    matching_coverage,

    case when rn >= 7 then round(avg(active_users) over w7, 2) end        as active_users_ma7,
    case when rn >= 7 then round(avg(new_users) over w7, 2) end           as new_users_ma7,
    case when rn >= 7 then round(avg(sessions) over w7, 2) end            as sessions_ma7,
    case when rn >= 7 then round(avg(page_views) over w7, 2) end          as page_views_ma7,
    case when rn >= 7 then round(avg(engagement_seconds) over w7, 2) end  as engagement_seconds_ma7,
    case when rn >= 7 then round((sum(engaged_sessions) over w7)::numeric
                                 / nullif((sum(sessions) over w7), 0), 4) end              as engagement_rate_ma7,
    case when rn >= 7 then round((sum(engagement_seconds) over w7)
                                 / nullif((sum(active_users) over w7), 0), 2) end          as engagement_seconds_per_user_ma7
    {%- for m in lagged %},
    lag({{ m }}, 7)   over wd as {{ m }}_p7,
    lag({{ m }}, 364) over wd as {{ m }}_py
    {%- endfor %}
from rated
window
    w7 as (order by date_day rows between 6 preceding and current row),
    wd as (order by date_day)
