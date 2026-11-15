"""fact_article_signal: segnali esterni di attenzione per articolo, formato lungo

Un segnale e' una misura di attenzione verso l'opera di cui parla l'articolo, presa
da una fonte esterna al nostro pubblico (Wikipedia, TMDB, IMDb, Google Trends,
YouTube, Trakt, Rotten Tomatoes). Grain: una riga per (articolo, fonte, metrica,
data di rilevazione, finestra, versione del metodo). Come fact_ga4_daily e' in
formato lungo: una fonte o una metrica nuova e' una riga in piu', non una colonna
(e nessuna migrazione). Un articolo senza una fonte semplicemente non ha quelle righe.

Il valore e' dell'OPERA, non dell'articolo: gli articoli che parlano della stessa
opera ricevono lo stesso valore. Non sommare tra articoli dello stesso titolo.

Metriche a finestra (visite Wikipedia, Google Trends): window_start/window_end
sono i giorni misurati. Metriche istantanee (popolarita' TMDB, voti IMDb, views
YouTube, spettatori Trakt, punteggi RT): window_start = window_end = as_of_date.
Le istantanee non hanno storico alla fonte: lo storico si costruisce con le
rilevazioni successive di questa tabella.

method_version: tag del metodo di raccolta/abbinamento, formato 'signals-v<N>'.
Va incrementato quando cambiano le regole di abbinamento titolo -> voce o la
definizione di una metrica.

Revision ID: 0006_fact_article_signal
Revises: 0005_article_score_period
Create Date: 2026-11-06

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0006_fact_article_signal"
down_revision = "0005_article_score_period"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE fact_article_signal (
            article_id      INTEGER      NOT NULL REFERENCES articles_dim(article_id) ON DELETE CASCADE,
            source          TEXT         NOT NULL CHECK (source IN (
                                             'wikipedia', 'tmdb', 'imdb', 'google_trends',
                                             'youtube', 'trakt', 'rotten_tomatoes'
                                         )),
            metric          TEXT         NOT NULL,
            as_of_date      DATE         NOT NULL,
            window_start    DATE         NOT NULL,
            window_end      DATE         NOT NULL,
            method_version  TEXT         NOT NULL,

            value           NUMERIC(20,6) NOT NULL,
            source_entry    TEXT,
            work_label      TEXT,

            computed_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),

            PRIMARY KEY (article_id, source, metric, as_of_date, window_start, window_end, method_version),
            CONSTRAINT chk_fact_article_signal_window CHECK (window_end >= window_start)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_fact_article_signal_lookup "
        "ON fact_article_signal(source, metric, as_of_date)"
    )
    op.execute(
        "COMMENT ON TABLE fact_article_signal IS "
        "$$Segnali esterni di attenzione verso l'opera trattata dall'articolo, in formato lungo "
        "(articolo, fonte, metrica, data, finestra, versione). Il valore e' dell'opera: non sommare "
        "tra articoli dello stesso titolo. Scritture idempotenti via ON CONFLICT sulla chiave primaria.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_article_signal.metric IS "
        "$$Nome della metrica nella fonte, es. views (Wikipedia), popularity (TMDB), votes (IMDb), "
        "interest_ratio (Google Trends), trailer_views (YouTube), watchers (Trakt), critics_pct (RT).$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_article_signal.window_start IS "
        "$$Primo giorno misurato. Per le metriche istantanee coincide con as_of_date.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_article_signal.source_entry IS "
        "$$Voce della fonte abbinata (pagina Wikipedia, titolo TMDB, id IMDb, URL, ...): serve a "
        "controllare gli abbinamenti.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_article_signal.method_version IS "
        "$$Tag del metodo di raccolta e abbinamento, formato 'signals-v<N>'.$$"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fact_article_signal")
