## Contesto

Sto costruendo la parte di storage di un data pipeline che ingerisce contenuti editoriali da un sito WordPress (via WP REST API) in un database PostgreSQL, seguendo uno star schema in stile Kimball. Ho già la DDL completa dello schema iniziale (vedi sotto) e mi serve solo l'infrastruttura per inizializzarlo e versionarlo, non la progettazione dello schema stesso (quella è già decisa e non va cambiata).

## Cosa mi serve

1. Un `docker-compose.yml` con **solo un servizio Postgres** (nessun container applicativo per Python/Alembic, quello lo lancio dall'host).
2. Setup di **Alembic** per gestire il versionamento dello schema, con queste caratteristiche:
   - Migration scritte in **SQL puro tramite `op.execute()`**, non modelli SQLAlchemy con autogenerate. Non voglio un layer ORM, solo Alembic come motore di versioning.
   - Una prima migration (`upgrade`/`downgrade`) che crea tutte le tabelle della DDL qui sotto, esattamente come sono, inclusi indici e commenti.
   - Struttura di cartelle standard Alembic (`alembic.ini`, `env.py`, `versions/`).
3. Istruzioni chiare per: far partire il container Postgres, configurare la connection string di Alembic verso quel container, eseguire `alembic upgrade head` la prima volta.

## Vincoli

- Non modificare lo schema, i nomi di tabelle/colonne, i tipi di dato o gli indici: la DDL sotto è già stata decisa e validata, va riportata fedelmente nella migration.
- Non introdurre un ORM o modelli dichiarativi: solo SQL puro dentro le funzioni Alembic.
- Il docker-compose deve esporre Postgres su una porta host configurabile e usare variabili d'ambiente per credenziali/nome DB (niente credenziali hardcoded nel file).
- Se servono estensioni Postgres (es. `pgcrypto`, `uuid-ossp`) valutale solo se strettamente necessarie per la DDL sotto: al momento non ce n'è bisogno, quindi non aggiungerle senza motivo.

## DDL di riferimento (da riportare fedelmente nella prima migration)

```sql
-- =====================================================================
-- SCHEMA: articles data model (taxidrivers.it)
-- Stile: Kimball star schema
-- Dimension: articles_dim, categories_dim
-- Bridge:    articles_categories (many-to-many)
-- Fact:      fact_ga4_daily, fact_gsc_daily (esistenti, grain giornaliero)
--            fact_wp_engagement_weekly (nuova, grain settimanale)
-- =====================================================================


-- ---------------------------------------------------------------------
-- DIMENSION: categories_dim
-- ---------------------------------------------------------------------
CREATE TABLE categories_dim (
    category_id        INTEGER PRIMARY KEY,
    parent_id           INTEGER REFERENCES categories_dim(category_id),
    name                TEXT NOT NULL,
    slug                TEXT NOT NULL UNIQUE,
    description         TEXT,
    wp_taxonomy         TEXT NOT NULL DEFAULT 'category',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_categories_dim_parent ON categories_dim(parent_id);
CREATE INDEX idx_categories_dim_taxonomy ON categories_dim(wp_taxonomy);

COMMENT ON TABLE categories_dim IS 'Dimension: categorie e tassonomie custom WordPress, gerarchia via parent_id (adjacency list)';
COMMENT ON COLUMN categories_dim.wp_taxonomy IS 'Distingue category standard da tassonomie custom (Recensioni, Serie TV, Festival...), da confermare via /wp/v2/taxonomies';


-- ---------------------------------------------------------------------
-- DIMENSION: articles_dim
-- ---------------------------------------------------------------------
CREATE TABLE articles_dim (
    article_id          INTEGER PRIMARY KEY,
    slug                TEXT NOT NULL UNIQUE,
    link                TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'publish',

    title                TEXT NOT NULL,
    excerpt              TEXT,
    content_html         TEXT,

    author_wp_id         INTEGER,
    author_name          TEXT,

    featured_media_url   TEXT,
    format               TEXT,
    comment_status       TEXT,

    published_at         TIMESTAMPTZ,
    modified_at           TIMESTAMPTZ,

    ingested_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_articles_dim_published_at ON articles_dim(published_at);
CREATE INDEX idx_articles_dim_author ON articles_dim(author_wp_id);
CREATE INDEX idx_articles_dim_status ON articles_dim(status);

COMMENT ON TABLE articles_dim IS 'Dimension: un articolo = una riga, attributi descrittivi stabili. Le metriche di performance vivono nelle fact table separate.';
COMMENT ON COLUMN articles_dim.content_html IS 'content.rendered integrale, serve da input per feature engineering testuale (word count, NLP)';
COMMENT ON COLUMN articles_dim.author_wp_id IS 'ID autore WordPress, denormalizzato: nessuna tabella authors dedicata per scelta di semplicita e privacy';


-- ---------------------------------------------------------------------
-- BRIDGE: articles_categories
-- ---------------------------------------------------------------------
CREATE TABLE articles_categories (
    article_id          INTEGER NOT NULL REFERENCES articles_dim(article_id) ON DELETE CASCADE,
    category_id          INTEGER NOT NULL REFERENCES categories_dim(category_id) ON DELETE CASCADE,
    PRIMARY KEY (article_id, category_id)
);

CREATE INDEX idx_articles_categories_category ON articles_categories(category_id);

COMMENT ON TABLE articles_categories IS 'Bridge many-to-many tra articles_dim e categories_dim';


-- ---------------------------------------------------------------------
-- FACT: fact_wp_engagement_weekly
-- Grain: una riga per articolo per settimana.
-- ---------------------------------------------------------------------
CREATE TABLE fact_wp_engagement_weekly (
    article_id           INTEGER NOT NULL REFERENCES articles_dim(article_id) ON DELETE CASCADE,
    week_start_date       DATE NOT NULL,

    comment_count          INTEGER NOT NULL DEFAULT 0,
    was_modified_in_week    BOOLEAN NOT NULL DEFAULT false,

    loaded_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

    PRIMARY KEY (article_id, week_start_date)
);

CREATE INDEX idx_fact_wp_engagement_weekly_week ON fact_wp_engagement_weekly(week_start_date);

COMMENT ON TABLE fact_wp_engagement_weekly IS 'Fact table grain settimanale: metriche di engagement native WP REST API (commenti, flag modifica). Grain diverso da fact_ga4_daily/fact_gsc_daily (giornaliere).';
COMMENT ON COLUMN fact_wp_engagement_weekly.week_start_date IS 'Lunedi della settimana ISO di riferimento, usato come chiave temporale al posto di una data singola';
```

## Nota

Le tabelle `fact_ga4_daily`, `fact_gsc_daily` e `article_features` esistono già concettualmente nel progetto ma la loro DDL non è inclusa qui: se vuoi proporre una migration separata per queste, chiedimi prima la loro struttura invece di inventarla.