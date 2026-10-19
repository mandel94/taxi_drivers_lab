-- Gli utenti unici di un periodo completo stanno tra il massimo dei giornalieri e la somma dei
-- giornalieri (la stessa persona che torna piu' giorni conta una volta sola nel periodo).
select
    p.period_type,
    p.period_start,
    p.active_users,
    max(d.active_users) as max_daily,
    sum(d.active_users) as sum_daily
from {{ ref('mart_site_period') }} p
join {{ ref('stg_ga4_site_daily') }} d
    on d.date_day between p.period_start and p.period_end
where p.is_complete
group by p.period_type, p.period_start, p.active_users
having p.active_users not between max(d.active_users) and sum(d.active_users)
