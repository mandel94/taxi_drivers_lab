-- Riconciliazione settimanale: sulla settimana lo scarto giornaliero si compensa, quindi la
-- tolleranza qui e' piu' stretta (1%). Solo settimane complete.
select
    d.week_start_date,
    sum(d.sessions) as site_sessions,
    sum(c.channel_sessions) as channel_sessions
from {{ ref('mart_site_daily') }} d
join (
    select date_day, sum(sessions) as channel_sessions
    from {{ ref('mart_channel_daily') }}
    group by date_day
) c using (date_day)
join {{ ref('int_week_spine') }} sp
    on sp.scope = 'site' and sp.week_start_date = d.week_start_date and sp.is_complete_week
group by d.week_start_date
having abs(sum(c.channel_sessions) - sum(d.sessions)) > 0.01 * greatest(sum(d.sessions), 1)
