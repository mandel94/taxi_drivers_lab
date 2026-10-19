"""restyle fact_ga4_daily: wide -> long, grain = (article_id, metric_date, metric_name)

Riscrivi la fact table GA4 in formato long (una riga per articolo, data e
metrica) con article_id come FK diretta verso articles_dim. La versione
precedente era in formato wide (8 colonne metriche fisse) e grainizzata su
page_path + event_date: i dati storici restano disponibili nella tabella
archiviata fact_ga4_daily_legacy_pagepath per forensics e rollback, e un
backfill best-effort trasferisce le sole righe il cui page_path risolve a
uno slug ancora presente in articles_dim.

Vincoli strutturali del nuovo schema:
- metric_date e' una singola DATE, non un intervallo: il grain e' per
  giorno civile, strutturalmente impossibile da estendere a un range.
- La PK (article_id, metric_date, metric_name) garantisce univocita' e
  idempotenza delle scritture: ON CONFLICT DO UPDATE.
- La CHECK constraint su metric_name blocca valori fuori vocabolario.
- Il CHECK strutturale sul grain giornaliero e' dato dal tipo DATE di
  metric_date: il dominio non ammette un range.

Revision ID: 0003_fact_ga4_daily_long_format
Revises: 0002_fact_ga4_daily
Create Date: 2026-09-10

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "0003_fact_ga4_daily_long_format"
down_revision = "0002_fact_ga4_daily"
branch_labels = None
depends_on = None


# Mappa metrica legacy (colonne wide) -> nome canonico nel formato long.
# Coerente con GA4_METRICS in ga4_client.py / ga4-service.js.
_METRICS = (
    "active_users",
    "screen_page_views",
    "sessions",
    "engaged_sessions",
    "engagement_rate",
    "bounce_rate",
    "average_session_duration",
    "user_engagement_duration",
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1) Drop delle viste che dipendono dalla vecchia struttura wide:
    #    article_id ora e' colonna nativa della fact, non serve piu'
    #    risolverlo via slug-match in una view.
    # ------------------------------------------------------------------
    op.execute("DROP VIEW IF EXISTS fact_ga4_unmatched;")
    op.execute("DROP VIEW IF EXISTS fact_ga4_daily_matched;")

    # ------------------------------------------------------------------
    # 2) Archiviazione della tabella legacy. Niente DROP: i dati
    #    storici restano disponibili per forensics o per un eventuale
    #    downgrade. Il nome rende esplicito il formato precedente
    #    (grain su page_path, non su article_id).
    # ------------------------------------------------------------------
    op.execute("ALTER TABLE fact_ga4_daily RENAME TO fact_ga4_daily_legacy_pagepath;")

    op.execute(
        "COMMENT ON TABLE fact_ga4_daily_legacy_pagepath IS "
        "$$Archivio della fact_ga4_daily pre-restyling (0003): formato wide, "
        "grain (page_path, event_date), otto colonne metriche fisse. I dati "
        "qui presenti non vengono piu' aggiornati: il backfill dei record "
        "risolvibili via slug e' gia' stato eseguito nella nuova fact_ga4_daily "
        "(formato long, grain per article_id). Usare questa tabella solo per "
        "diagnostica o recupero storico.$$"
    )

    # ------------------------------------------------------------------
    # 3) Creazione della nuova fact table in formato long.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE fact_ga4_daily (
            article_id    INTEGER      NOT NULL REFERENCES articles_dim(article_id),
            metric_date   DATE         NOT NULL,
            metric_name   TEXT         NOT NULL,
            metric_value  NUMERIC      NOT NULL,
            fetched_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
            PRIMARY KEY (article_id, metric_date, metric_name),
            CONSTRAINT chk_fact_ga4_daily_metric_name CHECK (metric_name IN (
                'active_users',
                'screen_page_views',
                'sessions',
                'engaged_sessions',
                'engagement_rate',
                'bounce_rate',
                'average_session_duration',
                'user_engagement_duration'
            ))
        )
        """
    )

    # Indici per i pattern di lettura piu' probabili.
    op.execute(
        "CREATE INDEX idx_fact_ga4_daily_date ON fact_ga4_daily(metric_date);"
    )
    op.execute(
        "CREATE INDEX idx_fact_ga4_daily_metric_name ON fact_ga4_daily(metric_name);"
    )

    op.execute(
        "COMMENT ON TABLE fact_ga4_daily IS "
        "$$Fact table GA4 in formato long: una riga per (article_id, metric_date, metric_name). "
        "Grain rigorosamente giornaliero: metric_date e' una singola DATE, non un intervallo. "
        "Strutturalmente impossibile memorizzare una misurazione su piu' di un giorno. "
        "Scritture idempotenti via INSERT ... ON CONFLICT (article_id, metric_date, metric_name) DO UPDATE.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_ga4_daily.metric_date IS "
        "$$Singolo giorno civile (DATE, no time, no range). Chiave temporale della fact: il grain e' giornaliero.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_ga4_daily.metric_name IS "
        "$$Nome della metrica GA4: il vocabolario e' fissato dalla CHECK constraint. "
        "Una riga per ogni combinazione (articolo, giorno, metrica).$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_ga4_daily.metric_value IS "
        "$$Valore numerico della metrica per (article_id, metric_date). "
        "Le unita' dipendono da metric_name: interi per active_users/sessions/etc., "
        "0-1 per engagement_rate/bounce_rate, secondi per *_duration.$$"
    )
    op.execute(
        "COMMENT ON COLUMN fact_ga4_daily.fetched_at IS "
        "$$Timestamp di quando la riga e' stata osservata/scritta. Distinto da metric_date: "
        "fetched_at cambia a ogni re-ingest (idempotenza), metric_date identifica il giorno a cui il dato si riferisce.$$"
    )

    # ------------------------------------------------------------------
    # 4) Backfill best-effort dalla tabella archiviata.
    #    Solo le righe il cui page_path si risolve in articles_dim.slug
    #    entrano nella nuova fact; le altre restano nella legacy per
    #    diagnostica (slug rinominati, pagine non-articolo, ecc.).
    #
    #    Una riga legacy -> 8 righe nuove (una per metrica).
    #    COALESCE a 0 per i campi NULLable nella legacy (engagement_rate,
    #    bounce_rate, *_duration) perche' la nuova colonna metric_value
    #    e' NOT NULL.
    #    ON CONFLICT DO NOTHING rende la migration idempotente.
    # ------------------------------------------------------------------
    _values_clause = ",\n            ".join(
        f"('{name}', l.{name})" for name in _METRICS
    )
    op.execute(
        f"""
        INSERT INTO fact_ga4_daily (article_id, metric_date, metric_name, metric_value, fetched_at)
        SELECT
            a.article_id,
            l.event_date,
            m.metric_name,
            COALESCE(m.metric_value, 0) AS metric_value,
            l.loaded_at AS fetched_at
        FROM fact_ga4_daily_legacy_pagepath l
        JOIN articles_dim a
            ON trim(both '/' FROM l.page_path) = a.slug
        CROSS JOIN LATERAL (VALUES
            {_values_clause}
        ) AS m(metric_name, metric_value)
        ON CONFLICT (article_id, metric_date, metric_name) DO NOTHING;
        """
    )


def downgrade() -> None:
    # 1) Drop della nuova tabella (e dei suoi indici, portati via).
    op.execute("DROP TABLE IF EXISTS fact_ga4_daily;")

    # 2) Ripristino della tabella legacy come fact_ga4_daily.
    #    Dati storici intatti (anche quelli non migrati al forward).
    op.execute(
        "ALTER TABLE fact_ga4_daily_legacy_pagepath RENAME TO fact_ga4_daily;"
    )

    # 3) Ricrea le viste originali definite in 0002, cosi' che il
    #    downgrade torni a uno stato funzionalmente equivalente al 0002.
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
