-- Un articolo pubblicato per riga. Non espone content_html, excerpt e campi autore: sono pesanti
-- e per l'autore la scelta di privacy gia' presa e' di non farne una dimensione.
-- word_count e' una stima: toglie i tag e conta le sequenze separate da spazi.
select
    a.article_id,
    a.slug,
    a.title,
    a.link,
    lower(regexp_replace(a.link, '^https?://[^/]+', ''))                         as url_path,
    a.published_date,
    coalesce(s.section_key, 'non_classificato')                                    as primary_section_key,
    coalesce(
        array_length(
            regexp_split_to_array(
                nullif(trim(regexp_replace(a.content_html, '<[^>]+>', ' ', 'g')), ''),
                '\s+'),
            1),
        0)                                                                         as word_count
from {{ ref('stg_articles') }} a
left join {{ ref('int_article_section') }} s
    on s.article_id = a.article_id
   and s.is_primary
