-- GA4 per articolo e giorno (sparso: solo le coppie con traffico), arricchito con sezione primaria
-- ed eta' dell'articolo. Non si densifica: articoli x giorni darebbe decine di milioni di righe
-- di zeri. L'assenza di una riga vale zero.
-- age_days ha un minimo di 0: alcune righe GA4 precedono la pubblicazione (anteprime del
-- redattore, fuso orario) e un'eta' negativa romperebbe le fasce.
select
    g.date_day,
    date_trunc('week', g.date_day::timestamp)::date                  as week_start_date,
    g.article_id,
    a.title,
    a.link,
    a.primary_section_key                                              as section_key,
    s.section_name,
    greatest(0, g.date_day - a.published_date)                         as age_days,
    {{ age_bucket('greatest(0, g.date_day - a.published_date)') }}     as age_bucket,
    greatest(0, g.date_day - a.published_date) < 30                    as is_new_30d,
    g.views,
    g.engagement_seconds,
    g.sessions_attributed,
    g.engaged_sessions_attributed
from {{ ref('stg_ga4_article_daily') }} g
join {{ ref('dim_article') }} a on a.article_id = g.article_id
join {{ ref('dim_section') }} s on s.section_key = a.primary_section_key
