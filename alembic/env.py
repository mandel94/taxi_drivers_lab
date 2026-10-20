from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from dotenv import load_dotenv

# Carica .env (se presente) dalla directory di lavoro: unica fonte di verita'
# condivisa con docker-compose. Le variabili d'ambiente dell'host, se gia'
# impostate, hanno precedenza su quelle definite in .env.
load_dotenv()

import os

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Nessun modello SQLAlchemy: questo progetto usa solo SQL puro nelle migration.
# target_metadata resta None di proposito (niente ORM, niente autogenerate).
target_metadata = None


def _build_database_url() -> str:
    """Costruisce la connection string verso il Postgres del docker-compose.

    Priorita':
      1. DATABASE_URL (se impostata esplicitamente)
      2. POSTGRES_* variabili (dal .env o dall'ambiente dell'host)
    """
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.environ["POSTGRES_PASSWORD"]
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5434")
    db = os.getenv("POSTGRES_DB", "postgres")

    return (
        f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"
    )


config.set_main_option("sqlalchemy.url", _build_database_url())


def run_migrations_offline() -> None:
    """Esegue le migration in modalita' 'offline' (genera solo SQL)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Esegue le migration contro il database (connessione reale)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
