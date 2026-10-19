-- Settimane (lunedi) coperte dai dati, per ciascun ambito, con il flag di settimana completa.
-- Una settimana e' completa se inizia dopo l'inizio della copertura e finisce prima degli ultimi
-- giorni provvisori: la prima settimana (dati che partono a meta') e l'ultima (in corso)
-- non lo sono, e non vanno confrontate come le altre.
select
    c.scope,
    d.week_start_date,
    (d.week_start_date >= c.start_date
     and d.week_start_date + 6 <= c.end_date - {{ var('provisional_days') }}) as is_complete_week
from {{ ref('int_coverage') }} c
join {{ ref('dim_date') }} d
    on d.date_day between c.start_date and c.end_date
group by c.scope, d.week_start_date, c.start_date, c.end_date
