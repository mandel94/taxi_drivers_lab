-- =====================================================================
-- FACT: fact_ga4_daily
-- Grain: una riga per page_path per giorno.
-- Contiene il dato GA4 grezzo (page_path cosi come restituito dalla
-- Data API), senza risoluzione di article_id: il matching verso
-- articles_dim avviene nella view fact_ga4_daily_matched, non qui.
--
-- Questo per tre motivi:
--   1. Fedelta alla fonte: fact_ga4_daily deve riflettere esattamente
--      cosa ha detto GA4, senza interpretazioni incorporate.
--   2. Reversibilita: se la logica di matching cambia in futuro (es.
--      si aggiungono gli slug storici via _wp_old_slug, oggi
--      volutamente non implementati per non introdurre complessita
--      non ancora necessaria), si ricalcola solo la view, senza
--      backfill sui dati gia scritti.
--   3. Debug: un path non abbinato resta visibile e ispezionabile,
--      invece di sparire dietro un article_id nullo o una riga scartata.
-- =====================================================================
CREATE TABLE fact_ga4_daily (
    page_path                TEXT NOT NULL,          -- pagePath grezzo da GA4 Data API, es. '/il-massacro-messeri/'
    event_date                DATE NOT NULL,

    active_users               INTEGER NOT NULL DEFAULT 0,
    screen_page_views           INTEGER NOT NULL DEFAULT 0,
    sessions                    INTEGER NOT NULL DEFAULT 0,
    engaged_sessions             INTEGER NOT NULL DEFAULT 0,
    engagement_rate               NUMERIC(6,4),          -- 0-1, es. 0.6421
    bounce_rate                   NUMERIC(6,4),          -- 0-1
    average_session_duration        NUMERIC(10,2),         -- secondi
    user_engagement_duration          NUMERIC(12,2),         -- secondi, totale aggregato del giorno

    loaded_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (page_path, event_date)
);

CREATE INDEX idx_fact_ga4_daily_event_date ON fact_ga4_daily(event_date);

COMMENT ON TABLE fact_ga4_daily IS 'Fact table grain giornaliero: metriche GA4 per page_path grezzo, cosi come restituito dalla Data API. Nessun article_id qui: il matching verso articles_dim vive nella view fact_ga4_daily_matched.';
COMMENT ON COLUMN fact_ga4_daily.page_path IS 'pagePath grezzo da GA4 (dimensione standard), es. /slug-articolo/. Non normalizzato in questa tabella.';
COMMENT ON COLUMN fact_ga4_daily.sessions IS 'ATTENZIONE: sessions, active_users, engagement_rate, bounce_rate, average_session_duration ed engaged_sessions sono metriche di sessione/utente riportate per pagina (attribuzione "a tocco": una sessione che visita piu pagine contribuisce a ciascuna). Sommare queste colonne su piu articoli NON torna al totale sessioni del sito. screen_page_views e user_engagement_duration sono invece genuinamente per-pagina e sommano correttamente.';


-- =====================================================================
-- VIEW: fact_ga4_daily_matched
-- Join tra fact_ga4_daily e articles_dim tramite match esatto sullo
-- slug corrente. Normalizza page_path (rimuove trailing/leading slash)
-- per confrontarlo con articles_dim.slug.
--
-- Limite noto e accettato per questa prima versione: un articolo che
-- ha cambiato slug nel tempo non aggancia le pageview GA4 registrate
-- con lo slug precedente (nessuna gestione di _wp_old_slug). I path
-- non abbinati restano visibili tramite fact_ga4_unmatched (sotto),
-- utile per misurare quanto pesa davvero questo limite prima di
-- eventualmente affrontarlo.
-- =====================================================================
CREATE VIEW fact_ga4_daily_matched AS
SELECT
    g.*,
    a.article_id,
    a.title
FROM fact_ga4_daily g
JOIN articles_dim a
    ON trim(both '/' FROM g.page_path) = a.slug;

COMMENT ON VIEW fact_ga4_daily_matched IS 'fact_ga4_daily arricchita con article_id, via match esatto sullo slug corrente di articles_dim. Righe con path non riconosciuto (slug cambiato, pagina non-articolo, ecc.) non compaiono qui: vedi fact_ga4_unmatched.';


-- =====================================================================
-- VIEW: fact_ga4_unmatched
-- Righe di fact_ga4_daily che NON trovano corrispondenza in articles_dim.
-- Serve a misurare l'entita del problema "slug cambiato nel tempo"
-- (o pagine non-articolo tracciate da GA4, es. homepage, tag, categorie)
-- prima di decidere se vale la pena gestire gli slug storici.
-- =====================================================================
CREATE VIEW fact_ga4_unmatched AS
SELECT g.*
FROM fact_ga4_daily g
WHERE NOT EXISTS (
    SELECT 1 FROM articles_dim a
    WHERE trim(both '/' FROM g.page_path) = a.slug
);

COMMENT ON VIEW fact_ga4_unmatched IS 'Diagnostica: page_path di fact_ga4_daily senza match in articles_dim. Usare per decidere se e quanto serve gestire slug storici o altri casi (pagine non-articolo).';