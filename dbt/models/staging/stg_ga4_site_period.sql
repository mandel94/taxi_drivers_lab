-- Si tengono solo i periodi che iniziano dalla copertura giornaliera: i periodi che la
-- precedono (ad es. la settimana a cavallo del 1 agosto 2025) hanno gli utenti di tutto il
-- periodo ma componenti giornalieri parziali, e darebbero rapporti sbagliati.
select
    period_type,
    period_start,
    period_end,
    is_complete,
    active_users,
    new_users,
    fetched_at
from {{ source('raw', 'fact_ga4_site_period') }}
where period_start >= '{{ var("ga4_site_start") }}'::date
