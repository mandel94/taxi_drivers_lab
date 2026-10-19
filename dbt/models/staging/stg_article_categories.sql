select
    article_id,
    category_id
from {{ source('raw', 'articles_categories') }}
