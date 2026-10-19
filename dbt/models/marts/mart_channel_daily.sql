-- Gruppo di canali per giorno, DENSO: ogni canale che compare nei dati e' presente in ogni giorno
-- coperto, anche con zero. L'elenco dei canali viene dai dati (non dal seed): un gruppo nuovo di
-- GA4 non va perso e la somma dei canali continua a tornare col totale di sito. Il seed dim_channel
-- fornisce solo etichetta italiana, ordine e is_organic; per i gruppi non ancora nel seed
-- l'etichetta e' il nome grezzo e is_organic si deduce dal prefisso "Organic".
-- Solo le sessioni sommano correttamente tra canali. active_users per canale NON si somma:
-- la stessa persona puo' arrivare da piu' canali in giorni diversi. Per questo non esiste
-- nessuna quota sugli utenti.
{% set lagged = ['sessions', 'engaged_sessions', 'page_views'] %}

with cov as (
    select start_date, end_date from {{ ref('int_coverage') }} where scope = 'site'
),

channels as (
    select distinct
        c.channel_group,
        coalesce(m.display_name, c.channel_group)                         as display_name,
        coalesce(m.sort_order, 999)                                       as sort_order,
        coalesce(m.is_organic, c.channel_group ilike 'organic%')          as is_organic
    from {{ ref('stg_ga4_channel_daily') }} c
    left join {{ ref('dim_channel') }} m on m.channel_group = c.channel_group
),

spine as (
    select d.date_day, d.week_start_date, ch.*
    from {{ ref('dim_date') }} d
    join cov on d.date_day between cov.start_date and cov.end_date
    cross join channels ch
),

daily as (
    select
        sp.date_day,
        sp.week_start_date,
        sp.channel_group,
        sp.display_name,
        sp.sort_order,
        sp.is_organic,
        coalesce(c.sessions, 0)                              as sessions,
        coalesce(c.engaged_sessions, 0)                      as engaged_sessions,
        coalesce(c.new_users, 0)                             as new_users,
        coalesce(c.page_views, 0)                            as page_views,
        coalesce(c.engagement_seconds, 0)::numeric(14,2)     as engagement_seconds,
        coalesce(c.active_users, 0)                          as active_users,
        row_number() over (partition by sp.channel_group order by sp.date_day) as rn
    from spine sp
    left join {{ ref('stg_ga4_channel_daily') }} c
        on c.date_day = sp.date_day and c.channel_group = sp.channel_group
)

select
    date_day,
    week_start_date,
    channel_group,
    display_name,
    sort_order,
    is_organic,
    sessions,
    engaged_sessions,
    new_users,
    page_views,
    engagement_seconds,
    active_users,
    round(engaged_sessions::numeric / nullif(sessions, 0), 4)                              as engagement_rate,
    round(sessions::numeric / nullif(sum(sessions) over (partition by date_day), 0), 4)    as sessions_share,
    date_day >= current_date - {{ var('provisional_days') }}                               as is_provisional,
    case when rn >= 7 then round(avg(sessions) over w7, 2) end                             as sessions_ma7,
    case when rn >= 7 then round((sum(engaged_sessions) over w7)::numeric
                                 / nullif((sum(sessions) over w7), 0), 4) end              as engagement_rate_ma7
    {%- for m in lagged %},
    lag({{ m }}, 7)   over wd as {{ m }}_p7,
    lag({{ m }}, 364) over wd as {{ m }}_py
    {%- endfor %}
from daily
window
    w7 as (partition by channel_group order by date_day rows between 6 preceding and current row),
    wd as (partition by channel_group order by date_day)
