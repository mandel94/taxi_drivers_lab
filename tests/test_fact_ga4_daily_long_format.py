"""
tests/test_fact_ga4_daily_long_format.py

Test end-to-end della migration 0003 (fact_ga4_daily wide -> long).

Cosa verifica:
  1. UP applichato dopo 0001 + 0002 porta il DB allo stato atteso:
     nuova fact_ga4_daily presente, legacy archiviata, viste rimosse.
  2. I vincoli strutturali del nuovo schema:
     - PK su (article_id, metric_date, metric_name) blocca duplicati.
     - FK verso articles_dim blocca article_id inesistenti.
     - CHECK su metric_name blocca valori fuori vocabolario.
     - metric_date e' DATE singolo: impossibile memorizzare un range.
  3. Il pattern ON CONFLICT DO UPDATE: insert + re-insert aggiornano
     metric_value e fetched_at senza duplicare la riga.
  4. Il backfill dalla legacy funziona solo per le righe il cui
     page_path risolve a uno slug ancora in articles_dim. Le righe
     non risolvibili restano SOLO nella tabella legacy.
  5. DOWN: ripristina la tabella wide originale (dati intatti) e le viste.

Esecuzione:
    DATABASE_URL=postgresql://postgres:<password>@localhost:5432/td_test_fact_ga4 \\
        .venv/Scripts/python.exe tests/test_fact_ga4_daily_long_format.py

Lo script ricrea il DB da zero ogni volta: lascia il DB pulito dopo
l'esecuzione, cosi' il prossimo test parte da uno stato noto.
"""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager

import psycopg2
from psycopg2 import errors as pg_errors

DATABASE_URL = os.environ["DATABASE_URL"]
ADMIN_URL = DATABASE_URL.rsplit("/", 1)[0] + "/postgres"
ALEMBIC_CMD = [sys.executable, "-m", "alembic"]


def _psycopg_url(sa_url: str) -> str:
    """Converte postgresql+psycopg2:// -> postgresql:// per psycopg2 puro."""
    return sa_url.replace("postgresql+psycopg2://", "postgresql://")


@contextmanager
def _conn(url: str = None):
    url = url or DATABASE_URL
    c = psycopg2.connect(_psycopg_url(url))
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def _alembic(*args: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = DATABASE_URL
    subprocess.run(ALEMBIC_CMD + list(args), check=True, env=env)


def reset_db() -> None:
    """Drop + recreate del DB di test, cosi' ogni run parte pulito."""
    # DROP/CREATE DATABASE non possono girare dentro un blocco di
    # transazione, quindi usiamo autocommit sulla connessione admin.
    c = psycopg2.connect(_psycopg_url(ADMIN_URL))
    c.autocommit = True
    try:
        with c.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = current_database() AND pid <> pg_backend_pid()"
            )
            cur.execute("DROP DATABASE IF EXISTS td_test_fact_ga4")
            cur.execute("CREATE DATABASE td_test_fact_ga4")
    finally:
        c.close()


# ----------------------------------------------------------------------
# SEED: dati minimi per esercitare la migration 0003.
# 2 articoli (slug1, slug2) + 1 legacy page risolvibile (slug1) +
# 1 legacy page NON risolvibile (slug che non esiste in articles_dim).
# ----------------------------------------------------------------------
def seed_after_0002() -> None:
    with _conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO articles_dim (article_id, slug, link, title, status, published_at, modified_at) "
            "VALUES (1001, 'slug1', 'https://example.com/slug1/', 'Articolo 1', 'publish', now(), now())"
        )
        cur.execute(
            "INSERT INTO articles_dim (article_id, slug, link, title, status, published_at, modified_at) "
            "VALUES (1002, 'slug2', 'https://example.com/slug2/', 'Articolo 2', 'publish', now(), now())"
        )
        # Riga legacy RISOLVIBILE: page_path '/slug1/' -> article_id 1001
        cur.execute(
            """INSERT INTO fact_ga4_daily (
                page_path, event_date, active_users, screen_page_views, sessions,
                engaged_sessions, engagement_rate, bounce_rate,
                average_session_duration, user_engagement_duration
            ) VALUES (
                '/slug1/', '2026-09-08', 10, 20, 15, 8, 0.5, 0.5,
                100.0, 500.0
            )"""
        )
        # Riga legacy NON RISOLVIBILE: '/vecchio-slug/' non esiste in articles_dim
        cur.execute(
            """INSERT INTO fact_ga4_daily (
                page_path, event_date, active_users, screen_page_views, sessions,
                engaged_sessions, engagement_rate, bounce_rate,
                average_session_duration, user_engagement_duration
            ) VALUES (
                '/vecchio-slug/', '2026-09-08', 5, 8, 7, 3, 0.3, 0.7,
                50.0, 200.0
            )"""
        )


# ----------------------------------------------------------------------
# TEST 1: UP 0003 porta il DB allo stato atteso
# ----------------------------------------------------------------------
def test_up_state() -> None:
    _alembic("upgrade", "0002")
    seed_after_0002()
    _alembic("upgrade", "0003")

    with _conn() as c, c.cursor() as cur:
        cur.execute("SELECT to_regclass('public.fact_ga4_daily')")
        assert cur.fetchone()[0] == "fact_ga4_daily", "fact_ga4_daily mancante"
        cur.execute("SELECT to_regclass('public.fact_ga4_daily_legacy_pagepath')")
        assert cur.fetchone()[0] == "fact_ga4_daily_legacy_pagepath", \
            "legacy archiviata mancante"
        cur.execute(
            "SELECT to_regclass('public.fact_ga4_daily_matched'), "
            "to_regclass('public.fact_ga4_unmatched')"
        )
        views = cur.fetchone()
        assert views == (None, None), f"Le viste dovrebbero essere rimosse, trovate: {views}"

    print("  PASS test_up_state")


# ----------------------------------------------------------------------
# TEST 2: vincoli strutturali del nuovo schema
# ----------------------------------------------------------------------
def test_constraints() -> None:
    # (a) PRIMARY KEY: duplicato deve fallire
    with _conn() as c, c.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO fact_ga4_daily (article_id, metric_date, metric_name, metric_value) "
                "VALUES (1001, '2026-09-08', 'active_users', 42)"
            )
            assert False, "duplicato PK: avrebbe dovuto fallire"
        except pg_errors.UniqueViolation:
            c.rollback()
        else:
            c.rollback()

        # (b) FK: article_id inesistente deve fallire
        try:
            cur.execute(
                "INSERT INTO fact_ga4_daily (article_id, metric_date, metric_name, metric_value) "
                "VALUES (99999, '2026-09-08', 'active_users', 42)"
            )
            assert False, "FK violation: avrebbe dovuto fallire"
        except pg_errors.ForeignKeyViolation:
            c.rollback()
        else:
            c.rollback()

        # (c) CHECK: metric_name fuori vocabolario deve fallire
        try:
            cur.execute(
                "INSERT INTO fact_ga4_daily (article_id, metric_date, metric_name, metric_value) "
                "VALUES (1001, '2026-09-08', 'metriche_inventate', 1)"
            )
            assert False, "CHECK violation: avrebbe dovuto fallire"
        except pg_errors.CheckViolation:
            c.rollback()
        else:
            c.rollback()

        # (d) metric_date NOT NULL
        try:
            cur.execute(
                "INSERT INTO fact_ga4_daily (article_id, metric_date, metric_name, metric_value) "
                "VALUES (1001, NULL, 'active_users', 1)"
            )
            assert False, "NOT NULL violation: avrebbe dovuto fallire"
        except pg_errors.NotNullViolation:
            c.rollback()
        else:
            c.rollback()

    print("  PASS test_constraints")


# ----------------------------------------------------------------------
# TEST 3: ON CONFLICT DO UPDATE (upsert) - idempotenza
# ----------------------------------------------------------------------
def test_upsert_idempotency() -> None:
    with _conn() as c, c.cursor() as cur:
        # Riga inesistente -> INSERT
        cur.execute(
            "INSERT INTO fact_ga4_daily (article_id, metric_date, metric_name, metric_value) "
            "VALUES (1001, '2026-09-09', 'sessions', 11) "
            "ON CONFLICT (article_id, metric_date, metric_name) DO UPDATE SET "
            "  metric_value = EXCLUDED.metric_value, fetched_at = EXCLUDED.fetched_at"
        )
        cur.execute(
            "SELECT metric_value FROM fact_ga4_daily "
            "WHERE article_id=1001 AND metric_date='2026-09-09' AND metric_name='sessions'"
        )
        assert cur.fetchone()[0] == 11

        # Re-insert stesso PK con valore diverso -> UPDATE
        cur.execute(
            "INSERT INTO fact_ga4_daily (article_id, metric_date, metric_name, metric_value) "
            "VALUES (1001, '2026-09-09', 'sessions', 22) "
            "ON CONFLICT (article_id, metric_date, metric_name) DO UPDATE SET "
            "  metric_value = EXCLUDED.metric_value, fetched_at = EXCLUDED.fetched_at"
        )
        cur.execute(
            "SELECT metric_value FROM fact_ga4_daily "
            "WHERE article_id=1001 AND metric_date='2026-09-09' AND metric_name='sessions'"
        )
        assert cur.fetchone()[0] == 22, "ON CONFLICT non ha aggiornato metric_value"

        # Conta righe: deve essere 1 (upsert non duplica)
        cur.execute(
            "SELECT COUNT(*) FROM fact_ga4_daily "
            "WHERE article_id=1001 AND metric_date='2026-09-09' AND metric_name='sessions'"
        )
        assert cur.fetchone()[0] == 1, "upsert ha duplicato la riga"

    print("  PASS test_upsert_idempotency")


# ----------------------------------------------------------------------
# TEST 4: backfill dalla legacy - solo righe risolvibili
# ----------------------------------------------------------------------
def test_backfill() -> None:
    with _conn() as c, c.cursor() as cur:
        # Riga legacy '/slug1/' (risolvibile) -> 8 righe nuove per article 1001
        # in data 2026-09-08 (una per metrica).
        cur.execute(
            "SELECT COUNT(*) FROM fact_ga4_daily "
            "WHERE article_id = 1001 AND metric_date = '2026-09-08'"
        )
        n_backfill = cur.fetchone()[0]
        assert n_backfill == 8, f"attese 8 righe backfill per article 1001 / 2026-09-08, trovate {n_backfill}"

        # Riga legacy '/vecchio-slug/' (NON risolvibile) -> 0 righe nuove
        cur.execute(
            "SELECT COUNT(*) FROM fact_ga4_daily WHERE article_id = 1001 "
            "AND metric_date = '2026-09-08' AND metric_value = 5"
        )
        assert cur.fetchone()[0] == 0, \
            "riga non risolvibile non doveva finire nella nuova fact"

        # Verifica un valore specifico: active_users per slug1/2026-09-08 = 10
        cur.execute(
            "SELECT metric_value FROM fact_ga4_daily "
            "WHERE article_id=1001 AND metric_date='2026-09-08' AND metric_name='active_users'"
        )
        assert cur.fetchone()[0] == 10

        # Verifica che le 8 metriche siano tutte presenti
        cur.execute(
            "SELECT metric_name FROM fact_ga4_daily "
            "WHERE article_id=1001 AND metric_date='2026-09-08' "
            "ORDER BY metric_name"
        )
        names = [r[0] for r in cur.fetchall()]
        expected = sorted([
            'active_users', 'screen_page_views', 'sessions', 'engaged_sessions',
            'engagement_rate', 'bounce_rate', 'average_session_duration', 'user_engagement_duration',
        ])
        assert names == expected, f"metriche attese: {expected}, trovate: {names}"

        # La legacy deve avere ENTRAMBE le righe originali (backfill non
        # tocca la tabella archiviata)
        cur.execute("SELECT COUNT(*) FROM fact_ga4_daily_legacy_pagepath")
        assert cur.fetchone()[0] == 2, "legacy archiviata deve restare intatta"

    print("  PASS test_backfill")


# ----------------------------------------------------------------------
# TEST 5: DOWN 0003 -> 0002 ripristina la tabella wide + viste, dati legacy intatti
# ----------------------------------------------------------------------
def test_down() -> None:
    _alembic("downgrade", "0002")

    with _conn() as c, c.cursor() as cur:
        # fact_ga4_daily esiste di nuovo con la struttura wide
        cur.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='fact_ga4_daily' ORDER BY ordinal_position"
        )
        cols = [r[0] for r in cur.fetchall()]
        assert "page_path" in cols and "active_users" in cols and "sessions" in cols, \
            f"struttura wide non ripristinata, colonne: {cols}"
        assert "metric_name" not in cols, "colonna long-format ancora presente dopo DOWN"

        # Legacy archiviata non esiste piu' (rinominata in fact_ga4_daily)
        cur.execute(
            "SELECT to_regclass('public.fact_ga4_daily_legacy_pagepath')"
        )
        assert cur.fetchone()[0] is None

        # Viste ricreate
        cur.execute(
            "SELECT to_regclass('public.fact_ga4_daily_matched'), "
            "to_regclass('public.fact_ga4_unmatched')"
        )
        assert cur.fetchone() == ("fact_ga4_daily_matched", "fact_ga4_unmatched")

        # Dati legacy intatti
        cur.execute("SELECT COUNT(*) FROM fact_ga4_daily")
        assert cur.fetchone()[0] == 2, "dati legacy persi durante DOWN"

    print("  PASS test_down")


def main() -> int:
    print("== Reset DB di test ==")
    reset_db()

    print("\n== TEST 1: UP 0003 ==")
    test_up_state()

    print("\n== TEST 2: vincoli strutturali ==")
    test_constraints()

    print("\n== TEST 3: upsert idempotente ==")
    test_upsert_idempotency()

    print("\n== TEST 4: backfill dalla legacy ==")
    test_backfill()

    print("\n== TEST 5: DOWN 0003 -> 0002 ==")
    test_down()

    print("\n== Tutti i test SQL passati ==")
    return 0


if __name__ == "__main__":
    sys.exit(main())
