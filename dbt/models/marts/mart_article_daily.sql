-- Articolo per giorno, SPARSO: solo le coppie con traffico (l'assenza di riga vale zero).
-- is_provisional marca gli ultimi giorni, che GA4 puo' ancora rivedere.
select
    date_day,
    week_start_date,
    article_id,
    title,
    link,
    section_key,
    section_name,
    age_days,
    age_bucket,
    is_new_30d,
    views,
    engagement_seconds,
    sessions_attributed,
    engaged_sessions_attributed,
    date_day >= current_date - {{ var('provisional_days') }} as is_provisional
from {{ ref('int_article_daily') }}
