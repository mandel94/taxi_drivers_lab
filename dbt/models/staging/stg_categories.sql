select
    category_id,
    parent_id,
    name,
    slug,
    wp_taxonomy
from {{ source('raw', 'categories_dim') }}
