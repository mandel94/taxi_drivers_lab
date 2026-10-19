-- Una riga per giorno, dal primo giorno con dati GA4 a fine anno prossimo.
-- Postgres: date_trunc('week', ...) restituisce il lunedi (settimana ISO).
-- generate_series su timestamp senza fuso, per non dipendere dal fuso della sessione.
select
    d::date                                   as date_day,
    date_trunc('week', d)::date               as week_start_date,
    date_trunc('month', d)::date              as month_start,
    extract(isoyear from d)::int              as iso_year,
    extract(week from d)::int                 as iso_week,
    extract(quarter from d)::int              as quarter,
    extract(isodow from d) in (6, 7)          as is_weekend
from generate_series(
        '{{ var("ga4_site_start") }}'::timestamp,
        date_trunc('year', current_date::timestamp) + interval '2 years' - interval '1 day',
        interval '1 day') as g(d)
