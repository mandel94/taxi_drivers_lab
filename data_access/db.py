"""
db.py

Connessione riusabile al PostgreSQL del warehouse. Stessa logica DSN gia'
usata in alembic/env.py e db_snapshot.py: DATABASE_URL se impostata,
altrimenti le variabili POSTGRES_* (dal .env o dall'ambiente host).

Nessun ORM: le letture usano SQLAlchemy core (engine, gia' presente come
dipendenza transitiva di Alembic) per un path pulito verso pandas, mentre
`get_connection` espone psycopg2 puro per eventuali pattern di scrittura.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Mapping

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine

_ENGINE_CACHE: dict[str, Engine] = {}


def _to_psycopg_url(url: str) -> str:
    """Rimuove il suffisso driver SQLAlchemy (+psycopg2) se presente."""
    return url.replace("postgresql+psycopg2://", "postgresql://")


def build_database_url(explicit: str | None = None) -> str:
    """Costruisce la DSN, con la stessa priorita' di alembic/env.py:
    1. DATABASE_URL esplicita, 2. variabili POSTGRES_* (da .env o ambiente).
    """
    if explicit:
        return _to_psycopg_url(explicit)

    load_dotenv()

    url = os.getenv("DATABASE_URL")
    if url:
        return _to_psycopg_url(url)

    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5434")
    db = os.getenv("POSTGRES_DB", "postgres")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


def get_engine(url: str | None = None) -> Engine:
    """Engine SQLAlchemy (core, no ORM) per le letture pandas."""
    dsn = build_database_url(url)
    engine = _ENGINE_CACHE.get(dsn)
    if engine is None:
        engine = create_engine(dsn)
        _ENGINE_CACHE[dsn] = engine
    return engine


@contextmanager
def get_connection(url: str | None = None):
    """Connessione psycopg2 pura (per scritture/transazioni), auto-chiusa."""
    conn = psycopg2.connect(build_database_url(url))
    try:
        yield conn
    finally:
        conn.close()


def query_df(
    sql: str,
    params: Mapping[str, Any] | list[Any] | None = None,
    url: str | None = None,
) -> pd.DataFrame:
    """Esegue una query di sola lettura e restituisce un DataFrame.

    `params` accetta un dict (stile `%(nome)s`) o una lista (stile `%s`),
    coerente con pandas.read_sql_query.
    """
    return pd.read_sql_query(sql, get_engine(url), params=params)
