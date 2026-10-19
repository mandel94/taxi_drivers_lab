"""fact_ga4_daily + view di matching su slug

Revision ID: 0002_fact_ga4_daily
Revises: 0001_articles_star_schema
Create Date: 2026-09-09

Introduce la fact table per le metriche GA4 (grain: page_path per giorno,
dato grezzo non risolto ad article_id) e due view:
  - fact_ga4_daily_matched: join con articles_dim tramite match esatto
    sullo slug corrente.
  - fact_ga4_unmatched: righe di fact_ga4_daily senza corrispondenza,
    utile per misurare quanto pesano gli slug cambiati nel tempo prima
    di decidere se gestirli (oggi volutamente non implementato).
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "0002_fact_ga4_daily"
down_revision = "0001_articles_star_schema"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE fact_ga4_daily (
            page_path                TEXT NOT NULL,
            event_date                DATE NOT NULL,

            active_users               INTEGER NOT NULL DEFAULT 0,
            screen_page_views           INTEGER NOT NULL DEFAULT 0,
            sessions                    INTEGER NOT NULL DEFAULT 0,
            engaged_sessions             INTEGER NOT NULL DEFAULT 0,
            engagement_rate               NUMERIC(6,4),
            bounce_rate                   NUMERIC(6,4),
            average_session_duration        NUMERIC(10,2),
            user_engagement_duration          NUMERIC(12,2),

            loaded_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),

            PRIMARY KEY (page_path, event_date)
        );
        """
    )

    op.execute(
        "CREATE INDEX idx_fact_ga4_daily_event_date ON fact_ga4_daily(event_date);"
    )

    op.execute(
        """
        COMMENT ON TABLE fact_ga4_daily IS
        'Fact table grain giornaliero: metriche GA4 per page_path grezzo, cosi come restituito dalla Data API. Nessun article_id qui: il matching verso articles_dim vive nella view fact_ga4_daily_matched.';
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN fact_ga4_daily.page_path IS
        'pagePath grezzo da GA4 (dimensione standard), es. /slug-articolo/. Non normalizzato in questa tabella.';
        """
    )
    op.execute(
        """
        COMMENT ON COLUMN fact_ga4_daily.sessions IS
        'ATTENZIONE: sessions, active_users, engagement_rate, bounce_rate, average_session_duration ed engaged_sessions sono metriche di sessione/utente riportate per pagina (attribuzione "a tocco": una sessione che visita piu pagine contribuisce a ciascuna). Sommare queste colonne su piu articoli NON torna al totale sessioni del sito. screen_page_views e user_engagement_duration sono invece genuinamente per-pagina e sommano correttamente.';
        """
    )

    op.execute(
        """
        CREATE VIEW fact_ga4_daily_matched AS
        SELECT
            g.*,
            a.article_id,
            a.title
        FROM fact_ga4_daily g
        JOIN articles_dim a
            ON trim(both '/' FROM g.page_path) = a.slug;
        """
    )
    op.execute(
        """
        COMMENT ON VIEW fact_ga4_daily_matched IS
        'fact_ga4_daily arricchita con article_id, via match esatto sullo slug corrente di articles_dim. Righe con path non riconosciuto (slug cambiato, pagina non-articolo, ecc.) non compaiono qui: vedi fact_ga4_unmatched.';
        """
    )

    op.execute(
        """
        CREATE VIEW fact_ga4_unmatched AS
        SELECT g.*
        FROM fact_ga4_daily g
        WHERE NOT EXISTS (
            SELECT 1 FROM articles_dim a
            WHERE trim(both '/' FROM g.page_path) = a.slug
        );
        """
    )
    op.execute(
        """
        COMMENT ON VIEW fact_ga4_unmatched IS
        'Diagnostica: page_path di fact_ga4_daily senza match in articles_dim. Usare per decidere se e quanto serve gestire slug storici o altri casi (pagine non-articolo).';
        """
    )


def downgrade():
    op.execute("DROP VIEW IF EXISTS fact_ga4_unmatched;")
    op.execute("DROP VIEW IF EXISTS fact_ga4_daily_matched;")
    op.execute("DROP TABLE IF EXISTS fact_ga4_daily;")
