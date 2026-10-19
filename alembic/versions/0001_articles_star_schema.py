"""create articles star schema

Schema iniziale in stile Kimball per il data model di taxidrivers.it.

Dimension: articles_dim, categories_dim
Bridge:    articles_categories (many-to-many)
Fact:      fact_wp_engagement_weekly (grain settimanale)

Revision ID: 0001_articles_star_schema
Revises:
Create Date: 2026-09-04

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "0001_articles_star_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # DIMENSION: categories_dim
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE categories_dim (
            category_id        INTEGER PRIMARY KEY,
            parent_id           INTEGER REFERENCES categories_dim(category_id),
            name                TEXT NOT NULL,
            slug                TEXT NOT NULL UNIQUE,
            description         TEXT,
            wp_taxonomy         TEXT NOT NULL DEFAULT 'category',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_categories_dim_parent ON categories_dim(parent_id)")
    op.execute(
        "CREATE INDEX idx_categories_dim_taxonomy ON categories_dim(wp_taxonomy)"
    )
    op.execute(
        "COMMENT ON TABLE categories_dim IS "
        "'Dimension: categorie e tassonomie custom WordPress, gerarchia via parent_id (adjacency list)'"
    )
    op.execute(
        "COMMENT ON COLUMN categories_dim.wp_taxonomy IS "
        "'Distingue category standard da tassonomie custom (Recensioni, Serie TV, Festival...), da confermare via /wp/v2/taxonomies'"
    )

    # ------------------------------------------------------------------
    # DIMENSION: articles_dim
    # ------------------------------------------------------------------
    op.execute(
        """
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
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_articles_dim_published_at ON articles_dim(published_at)"
    )
    op.execute("CREATE INDEX idx_articles_dim_author ON articles_dim(author_wp_id)")
    op.execute("CREATE INDEX idx_articles_dim_status ON articles_dim(status)")
    op.execute(
        "COMMENT ON TABLE articles_dim IS "
        "'Dimension: un articolo = una riga, attributi descrittivi stabili. Le metriche di performance vivono nelle fact table separate.'"
    )
    op.execute(
        "COMMENT ON COLUMN articles_dim.content_html IS "
        "'content.rendered integrale, serve da input per feature engineering testuale (word count, NLP)'"
    )
    op.execute(
        "COMMENT ON COLUMN articles_dim.author_wp_id IS "
        "'ID autore WordPress, denormalizzato: nessuna tabella authors dedicata per scelta di semplicita e privacy'"
    )

    # ------------------------------------------------------------------
    # BRIDGE: articles_categories
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE articles_categories (
            article_id          INTEGER NOT NULL REFERENCES articles_dim(article_id) ON DELETE CASCADE,
            category_id          INTEGER NOT NULL REFERENCES categories_dim(category_id) ON DELETE CASCADE,
            PRIMARY KEY (article_id, category_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_articles_categories_category ON articles_categories(category_id)"
    )
    op.execute(
        "COMMENT ON TABLE articles_categories IS "
        "'Bridge many-to-many tra articles_dim e categories_dim'"
    )

    # ------------------------------------------------------------------
    # FACT: fact_wp_engagement_weekly
    # Grain: una riga per articolo per settimana.
    # ------------------------------------------------------------------
    op.execute(
        """
        CREATE TABLE fact_wp_engagement_weekly (
            article_id           INTEGER NOT NULL REFERENCES articles_dim(article_id) ON DELETE CASCADE,
            week_start_date       DATE NOT NULL,

            comment_count          INTEGER NOT NULL DEFAULT 0,
            was_modified_in_week    BOOLEAN NOT NULL DEFAULT false,

            loaded_at              TIMESTAMPTZ NOT NULL DEFAULT now(),

            PRIMARY KEY (article_id, week_start_date)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_fact_wp_engagement_weekly_week "
        "ON fact_wp_engagement_weekly(week_start_date)"
    )
    op.execute(
        "COMMENT ON TABLE fact_wp_engagement_weekly IS "
        "'Fact table grain settimanale: metriche di engagement native WP REST API (commenti, flag modifica). Grain diverso da fact_ga4_daily/fact_gsc_daily (giornaliere).'"
    )
    op.execute(
        "COMMENT ON COLUMN fact_wp_engagement_weekly.week_start_date IS "
        "'Lunedi della settimana ISO di riferimento, usato come chiave temporale al posto di una data singola'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE fact_wp_engagement_weekly")
    op.execute("DROP TABLE articles_categories")
    op.execute("DROP TABLE articles_dim")
    op.execute("DROP TABLE categories_dim")
