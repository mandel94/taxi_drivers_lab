-- Le visualizzazioni attribuite agli articoli non possono superare quelle del sito nello stesso giorno.
select
    date_day,
    articles_views,
    page_views
from {{ ref('mart_site_daily') }}
where articles_views is not null
  and articles_views > page_views
