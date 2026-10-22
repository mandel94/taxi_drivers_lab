"""fact_article_score_period: score editoriale e dimensioni di periodo per articolo

Lo score editoriale non e' un attributo dell'articolo: e' una misura relativa
calcolata sull'insieme di articoli di un periodo (percentile rank, winsorization
sul dataset). Per questo non va in articles_dim, che resta descrittivo, ma in
una fact table con grain (articolo, periodo, versione del metodo).

Contenuto della fact:
  - input GA4 del periodo (snapshot): active_users, screen_page_views,
    sessions, engaged_sessions, engagement_rate, bounce_rate,
    average_session_duration, user_engagement_duration. Lo snapshot serve a
    rendere ricalcolabile lo score. active_users per periodo non e' sommabile
    dai giornalieri (utenti unici), quindi va salvato qui.
  - rank percentili delle tre feature (reach, engagement, depth), calcolati
    sul dataset del periodo: non ricalcolabili senza gli altri articoli.
  - editorial_score (0-100), editorial_rank, content_segment.

Non salvati perche' derivabili: feature_reach (log1p di active_users),
feature_engagement (= engagement_rate), feature_depth (= average_session_duration),
segment_priority (funzione di content_segment), anomaly_flag (sempre False).

method_version: tag del metodo di calcolo (scoring + segmentazione), formato
'<strategia>-v<N>', es. 'balanced-v2'. Va incrementato quando cambia la formula
dello score, la winsorization, la metrica di reach o le regole di segmentazione.
Righe con versioni diverse convivono nella stessa tabella: il confronto storico
avviene filtrando per versione.

Revision ID: 0005_article_score_period
Revises: 0004_ga4_site_tables
Create Date: 2026-10-22

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0005_article_score_period"
down_revision = "0004_ga4_site_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE fact_article_score_period (
            article_id                 INTEGER      NOT NULL REFERENCES articles_dim(article_id) ON DELETE CASCADE,
            period_start               DATE         NOT NULL,
            period_end                 DATE         NOT NULL,
            method_version             TEXT         NOT NULL,

            active_users               INTEGER      NOT NULL DEFAULT 0 CHECK (active_users >= 0),
            screen_page_views          INTEGER      NOT NULL DEFAULT 0 CHECK (screen_page_views >= 0),
            sessions                   INTEGER      NOT NULL DEFAULT 0 CHECK (sessions >= 0),
            engaged_sessions           INTEGER      NOT NULL DEFAULT 0 CHECK (engaged_sessions >= 0),
            engagement_rate            NUMERIC(7,6) NOT NULL DEFAULT 0 CHECK (engagement_rate BETWEEN 0 AND 1),
            bounce_rate                NUMERIC(7,6) NOT NULL DEFAULT 0 CHECK (bounce_rate BETWEEN 0 AND 1),
            average_session_duration   NUMERIC(14,4) NOT NULL DEFAULT 0 CHECK (average_session_duration >= 0),
            user_engagement_duration   NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (user_engagement_duration >= 0),

            reach_rank                 NUMERIC(7,6) NOT NULL CHECK (reach_rank BETWEEN 0 AND 1),
            engagement_rank            NUMERIC(7,6) NOT NULL CHECK (engagement_rank BETWEEN 0 AND 1),
            depth_rank                 NUMERIC(7,6) NOT NULL CHECK (depth_rank BETWEEN 0 AND 1),

            editorial_score            NUMERIC(8,4) NOT NULL CHECK (editorial_score BETWEEN 0 AND 100),
            editorial_rank             INTEGER      NOT NULL CHECK (editorial_rank >= 1),
            content_segment            TEXT         NOT NULL CHECK (content_segment IN (
                                           'Champions',
                                           'Rough Diamonds',
                                           'Clickbait',
                                           'Dead Weight'
                                       )),

            computed_at                TIMESTAMPTZ  NOT NULL DEFAULT now(),

            PRIMARY KEY (article_id, period_start, period_end, method_version),
            CONSTRAINT chk_fact_article_score_period_range CHECK (period_end >= period_start)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_fact_article_score_period_rank "
        "ON fact_article_score_period(period_start, period_end, method_version, editorial_rank)"
    )
    op.execute(
        "COMMENT ON TABLE fact_article_score_period IS "
        "$$Score editoriale e input GA4 di un articolo su un periodo (intervallo [period_start, period_end]), "
        "con il tag del metodo di calcolo. Lo score e' relativo al dataset del periodo: cambia se cambia "
        "il set di articoli, quindi va letto insieme a period_start/period_end. Scritture idempotenti via "
        "ON CONFLICT (article_id, period_start, period_end, method_version) DO UPDATE.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_article_score_period.method_version IS "
        "$$Tag del metodo di calcolo (scoring e segmentazione), formato '<strategia>-v<N>'. "
        "Incrementare N quando cambiano formula, winsorization, metrica di reach o regole di segmentazione.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_article_score_period.active_users IS "
        "$$Utenti unici dell'articolo nel periodo, letti da GA4 sull'intervallo. Non sommare tra periodi.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_article_score_period.reach_rank IS "
        "$$Percentile rank 0-1 di log(1 + active_users) nel dataset del periodo.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_article_score_period.engagement_rank IS "
        "$$Percentile rank 0-1 di engagement_rate nel dataset del periodo.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_article_score_period.depth_rank IS "
        "$$Percentile rank 0-1 di average_session_duration nel dataset del periodo.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_article_score_period.editorial_score IS "
        "$$Score 0-100: (0.35 * reach_rank + 0.35 * engagement_rank + 0.30 * depth_rank) * 100.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_article_score_period.content_segment IS "
        "$$Quadrante reach/engagement rispetto alla mediana del periodo: Champions (alto/alto), "
        "Rough Diamonds (basso reach, alto engagement), Clickbait (alto reach, basso engagement), "
        "Dead Weight (basso/basso).$$"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fact_article_score_period")
