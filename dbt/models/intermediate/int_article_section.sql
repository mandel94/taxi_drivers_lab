-- Tutte le appartenenze articolo-sezione, con la sezione primaria: per i grafici per sezione
-- conta una sola sezione per articolo, quella con priority piu' bassa nel seed dim_section.
-- Le appartenenze multiple restano qui per le domande sulla copertura.
with mapped as (
    select
        ac.article_id,
        sc.section_key
    from {{ ref('stg_article_categories') }} ac
    join {{ ref('int_section_categories') }} sc on sc.category_id = ac.category_id
    group by ac.article_id, sc.section_key
),

ranked as (
    select
        m.article_id,
        m.section_key,
        s.priority,
        row_number() over (
            partition by m.article_id
            order by s.priority, m.section_key
        ) as rn
    from mapped m
    join {{ ref('dim_section') }} s on s.section_key = m.section_key
)

select
    article_id,
    section_key,
    priority,
    rn = 1 as is_primary
from ranked
