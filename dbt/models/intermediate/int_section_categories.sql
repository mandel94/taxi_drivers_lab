-- Per ogni sezione, l'insieme delle categorie che ne fanno parte: quelle del seed piu', dove
-- include_children e' vero, tutti i discendenti (query ricorsiva sulla gerarchia parent_id).
-- `union` e non `union all`: se due categorie si puntassero a vicenda per un errore nei dati,
-- la deduplica fa fermare la ricorsione invece di farla girare all'infinito.
with recursive tree as (
    select
        m.section_key,
        c.category_id,
        m.include_children
    from {{ ref('section_category_map') }} m
    join {{ ref('stg_categories') }} c on c.category_id = m.category_id

    union

    select
        t.section_key,
        c.category_id,
        t.include_children
    from tree t
    join {{ ref('stg_categories') }} c on c.parent_id = t.category_id
    where t.include_children
)

select distinct
    section_key,
    category_id
from tree
