-- Solo articoli pubblicati. published_date e' convertita in fuso di Roma: GA4 data i giorni nel
-- fuso della property, mentre published_at e' un timestamptz in UTC. Senza conversione un
-- articolo uscito alle 00:30 italiane finirebbe nel giorno prima.
select
    article_id,
    slug,
    link,
    title,
    status,
    published_at,
    (published_at at time zone 'Europe/Rome')::date as published_date,
    modified_at,
    updated_at,
    content_html
from {{ source('raw', 'articles_dim') }}
where status = 'publish'
  and published_at is not null
