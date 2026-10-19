"""tabelle GA4 di sito, canale e periodo + etl_run_log

Colma le mancanze strutturali che fact_ga4_daily (per articolo) non puo'
coprire: le metriche di sessione/utente per articolo sono attribuite "a
tocco" e non sommano al totale del sito, e non esiste alcuna dimensione
canale.

Nuove tabelle (formato largo: poche righe al giorno, rapporti ricalcolati
dai componenti a valle, mai salvati):
  - fact_ga4_site_daily:    totali di sito, grain giorno
  - fact_ga4_channel_daily: totali per gruppo di canali, grain giorno x canale
  - fact_ga4_site_period:   utenti unici su settimana/mese (non derivabili
                            dai giornalieri)
  - etl_run_log:            una riga per esecuzione di un job di ingestione

Vincoli volutamente pochi: nel raw solo cio' che non puo' essere vero in
nessun caso (conteggi negativi). Le invarianti di dominio vanno nei test
dbt con severita' warn, cosi' una revisione dei dati GA4 non fa fallire il
caricamento.

Revision ID: 0004_ga4_site_tables
Revises: 0003_fact_ga4_daily_long_format
Create Date: 2026-10-19

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0004_ga4_site_tables"
down_revision = "0003_fact_ga4_daily_long_format"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # fact_ga4_site_daily: totali di sito, una riga per giorno.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE fact_ga4_site_daily (
            metric_date                DATE PRIMARY KEY,
            active_users               INTEGER NOT NULL DEFAULT 0 CHECK (active_users >= 0),
            new_users                  INTEGER NOT NULL DEFAULT 0 CHECK (new_users >= 0),
            sessions                   INTEGER NOT NULL DEFAULT 0 CHECK (sessions >= 0),
            engaged_sessions           INTEGER NOT NULL DEFAULT 0 CHECK (engaged_sessions >= 0),
            screen_page_views          INTEGER NOT NULL DEFAULT 0 CHECK (screen_page_views >= 0),
            user_engagement_duration   NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (user_engagement_duration >= 0),
            fetched_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE fact_ga4_site_daily IS "
        "$$Totali di sito GA4, una riga per giorno civile (dimensione date, nessun'altra). "
        "Sono i totali veri del sito: a differenza di fact_ga4_daily, le sessioni qui non sono "
        "attribuite per pagina. Nessun rapporto salvato: engagement rate = engaged_sessions / sessions. "
        "Scritture idempotenti via ON CONFLICT (metric_date) DO UPDATE.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_ga4_site_daily.active_users IS "
        "$$Utenti attivi del giorno. NON si somma tra giorni: la stessa persona torna piu volte. "
        "Per utenti unici su settimana/mese usare fact_ga4_site_period.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_ga4_site_daily.user_engagement_duration IS "
        "$$Secondi totali di coinvolgimento (somma, non media).$$"
    )

    # ------------------------------------------------------------------
    # fact_ga4_channel_daily: totali per gruppo di canali, giorno x canale.
    # channel_group senza CHECK: GA4 puo' aggiungere gruppi e il caricamento
    # non deve fallire. Un test dbt (warn) segnala i valori non in dim_channel.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE fact_ga4_channel_daily (
            metric_date                DATE NOT NULL,
            channel_group              TEXT NOT NULL,
            active_users               INTEGER NOT NULL DEFAULT 0 CHECK (active_users >= 0),
            new_users                  INTEGER NOT NULL DEFAULT 0 CHECK (new_users >= 0),
            sessions                   INTEGER NOT NULL DEFAULT 0 CHECK (sessions >= 0),
            engaged_sessions           INTEGER NOT NULL DEFAULT 0 CHECK (engaged_sessions >= 0),
            screen_page_views          INTEGER NOT NULL DEFAULT 0 CHECK (screen_page_views >= 0),
            user_engagement_duration   NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (user_engagement_duration >= 0),
            fetched_at                 TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (metric_date, channel_group)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_fact_ga4_channel_daily_channel "
        "ON fact_ga4_channel_daily(channel_group)"
    )
    op.execute(
        "COMMENT ON TABLE fact_ga4_channel_daily IS "
        "$$Totali GA4 per gruppo di canali predefinito (organic, direct, ...), una riga per giorno e canale. "
        "Dimensione GA4 usata: sessionDefaultChannelGroup (scelta fissata prima del backfill: cambiarla "
        "dopo spezzerebbe lo storico). Il caricamento e' 'cancella e reinserisci' sull'intervallo "
        "richiesto, non un semplice upsert: se GA4 rivede un giorno e un gruppo sparisce o cambia nome, "
        "le righe vecchie non devono restare orfane.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_ga4_channel_daily.channel_group IS "
        "$$Valore grezzo di sessionDefaultChannelGroup (es. 'Organic Search', 'Direct', 'Unassigned'). "
        "Nessuna CHECK sui valori: l'elenco noto vive nel seed dbt dim_channel.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_ga4_channel_daily.active_users IS "
        "$$ATTENZIONE: NON si somma tra canali (la stessa persona puo comparire in piu gruppi) ne tra giorni. "
        "sessions, engaged_sessions, new_users, screen_page_views e user_engagement_duration sommano "
        "correttamente tra canali e riconciliano col totale di fact_ga4_site_daily.$$"
    )

    # ------------------------------------------------------------------
    # fact_ga4_site_period: utenti unici su un intervallo (settimana o mese).
    # Non derivabili dai giornalieri: GA4 va interrogato con l'intervallo
    # del periodo e senza dimensione data.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE fact_ga4_site_period (
            period_type    TEXT NOT NULL CHECK (period_type IN ('week', 'month')),
            period_start   DATE NOT NULL,
            period_end     DATE NOT NULL,
            active_users   INTEGER NOT NULL DEFAULT 0 CHECK (active_users >= 0),
            new_users      INTEGER NOT NULL DEFAULT 0 CHECK (new_users >= 0),
            is_complete    BOOLEAN NOT NULL,
            fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (period_type, period_start),
            CONSTRAINT chk_fact_ga4_site_period_range CHECK (period_end >= period_start)
        )
        """
    )
    op.execute(
        "COMMENT ON TABLE fact_ga4_site_period IS "
        "$$Utenti unici di sito su una settimana (lunedi-domenica, come week_start_date) o su un mese. "
        "Il valore e' letto da GA4 con l'intervallo del periodo, non sommato dai giornalieri. "
        "Il periodo in corso ha is_complete = false e viene riscritto a ogni esecuzione.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_ga4_site_period.active_users IS "
        "$$Utenti unici del periodo: sta tra il massimo dei giornalieri e la somma dei giornalieri.$$"
    )

    # ------------------------------------------------------------------
    # etl_run_log: una riga per esecuzione di un job di ingestione.
    # Alimenta mart_data_health (freschezza e fallimenti).
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE etl_run_log (
            run_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source          TEXT NOT NULL,
            started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at     TIMESTAMPTZ,
            date_from       DATE,
            date_to         DATE,
            rows_written    INTEGER,
            status          TEXT NOT NULL DEFAULT 'running'
                            CHECK (status IN ('running', 'success', 'failed')),
            error_message   TEXT
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_etl_run_log_source_started "
        "ON etl_run_log(source, started_at DESC)"
    )
    op.execute(
        "COMMENT ON TABLE etl_run_log IS "
        "$$Registro delle esecuzioni dei job di ingestione, una riga per fonte (es. ga4_site_daily, "
        "ga4_channel_daily, ga4_site_period). Scritto dai job stessi: 'running' all'avvio, poi "
        "'success' o 'failed' con error_message. Una riga rimasta 'running' indica un job interrotto.$$"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS etl_run_log")
    op.execute("DROP TABLE IF EXISTS fact_ga4_site_period")
    op.execute("DROP TABLE IF EXISTS fact_ga4_channel_daily")
    op.execute("DROP TABLE IF EXISTS fact_ga4_site_daily")
