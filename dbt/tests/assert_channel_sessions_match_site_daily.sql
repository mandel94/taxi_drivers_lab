-- Riconciliazione: le sessioni dei canali devono sommare a quelle del sito, giorno per giorno.
-- Tolleranza 5%: sui dati reali GA4 lo scarto giornaliero oscilla (media vicina a zero, segno
-- variabile, massimo osservato 3,45%), probabilmente per l'attribuzione di sessioni a cavallo
-- della mezzanotte. Uno scarto sistematico o molto piu' grande indica un errore di caricamento.
-- Esclusi i giorni provvisori.
select
    s.date_day,
    s.sessions as site_sessions,
    c.channel_sessions
from {{ ref('mart_site_daily') }} s
join (
    select date_day, sum(sessions) as channel_sessions
    from {{ ref('mart_channel_daily') }}
    group by date_day
) c using (date_day)
where not s.is_provisional
  and abs(c.channel_sessions - s.sessions) > 0.05 * greatest(s.sessions, 1)
