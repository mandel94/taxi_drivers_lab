select
    metric_date as date_day,
    channel_group,
    active_users,
    new_users,
    sessions,
    engaged_sessions,
    screen_page_views as page_views,
    user_engagement_duration as engagement_seconds,
    fetched_at
from {{ source('raw', 'fact_ga4_channel_daily') }}
where metric_date >= '{{ var("ga4_site_start") }}'::date
