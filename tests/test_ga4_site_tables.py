"""
tests/test_ga4_site_tables.py

Test end-to-end della migration 0004 (tabelle GA4 di sito, canale, periodo,
etl_run_log) e di ga4_client/ingest_ga4_site.py, con un client GA4 finto:
nessuna chiamata all'API e nessun accesso al database di lavoro.

Cosa verifica:
  1. UP: dopo 0001..0004 esistono le 4 tabelle e alembic_version = 0004.
  2. Vincoli: conteggi negativi, period_type fuori vocabolario, intervallo
     invertito, status del log fuori vocabolario e PK duplicata vengono rifiutati.
  3. Funzioni pure: resolve_range, iter_weeks, iter_months, build_periods.
  4. Ingestione con client finto: tipi convertiti, data malformata scartata,
     canale vuoto etichettato '(not set)', riconciliazione sessioni canali = sito,
     periodi con is_complete corretto, nessuna query oltre ieri, etl_run_log.
  5. Idempotenza: rilancio senza duplicati.
  6. Canali "cancella e reinserisci": un gruppo sparito in una revisione non
     resta orfano.
  7. Risposta vuota di GA4: la fonte fallisce, non cancella nulla e il log lo dice.
  8. Pianificazione --auto dal DB (sito/canali/periodi e articoli): giorni mancanti,
     buchi in mezzo e ultimi giorni rivisti.
  9. DOWN poi UP: la migration e' reversibile.

Esecuzione (dalla root del repo, con il Postgres del docker-compose attivo):
    .venv/Scripts/python.exe tests/test_ga4_site_tables.py

Usa le credenziali di .env ma un database dedicato, td_test_ga4_site, che viene
ricreato da zero a ogni esecuzione. Il database di lavoro non viene toccato.
"""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from argparse import Namespace
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import psycopg2
from dotenv import load_dotenv
from psycopg2 import errors as pg_errors

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ga4_client"))
load_dotenv(ROOT / ".env")

import ingest_ga4_site as ing  # noqa: E402

SCRATCH_DB = "td_test_ga4_site"
_user = os.getenv("POSTGRES_USER", "postgres")
_password = quote_plus(os.getenv("POSTGRES_PASSWORD", "postgres"))
_host = os.getenv("POSTGRES_HOST", "localhost")
_port = os.getenv("POSTGRES_PORT", "5434")
_base = f"postgresql://{_user}:{_password}@{_host}:{_port}"
DATABASE_URL = f"{_base}/{SCRATCH_DB}"
ADMIN_URL = f"{_base}/postgres"

TODAY = dt.date(2026, 10, 19)  # un lunedi: ieri (18) e' la domenica che chiude la settimana
YESTERDAY = TODAY - dt.timedelta(days=1)


@contextmanager
def _conn(url: str = DATABASE_URL):
    c = psycopg2.connect(url)
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
    subprocess.run(
        [sys.executable, "-m", "alembic", *args], check=True, env=env, cwd=ROOT,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def reset_db() -> None:
    c = psycopg2.connect(ADMIN_URL)
    c.autocommit = True
    try:
        with c.cursor() as cur:
            cur.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH_DB,)
            )
            cur.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB}")
            cur.execute(f"CREATE DATABASE {SCRATCH_DB}")
    finally:
        c.close()


def scalar(sql: str, params=()):
    with _conn() as c, c.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row[0] if row else None


def rows(sql: str, params=()):
    with _conn() as c, c.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def expect_error(exc_type, sql: str, params=()) -> None:
    try:
        with _conn() as c, c.cursor() as cur:
            cur.execute(sql, params)
    except exc_type:
        return
    raise AssertionError(f"atteso {exc_type.__name__} per: {sql}")


# ----------------------------------------------------------------------
# Client GA4 finto: restituisce stringhe, come il vero run_query.
# ----------------------------------------------------------------------
class FakeClient:
    def __init__(self, site_df, channel_df):
        self.site_df = site_df
        self.channel_df = channel_df
        self.calls: list[dict] = []

    def run_query(self, property_id, metrics, dimensions=None, start_date="", end_date="", **_):
        self.calls.append(
            {"dimensions": dimensions, "start": start_date, "end": end_date, "metrics": metrics}
        )
        if dimensions is None:
            days = (dt.date.fromisoformat(end_date) - dt.date.fromisoformat(start_date)).days + 1
            return pd.DataFrame({"activeUsers": [str(days * 100)], "newUsers": [str(days * 40)]})
        if dimensions == ["date"]:
            return self.site_df
        if dimensions == ["date", ing.CHANNEL_DIMENSION]:
            return self.channel_df
        raise AssertionError(f"dimensioni inattese: {dimensions}")


SITE_COLS = ["date", *ing.GA4_METRICS]
CHANNEL_COLS = ["date", ing.CHANNEL_DIMENSION, *ing.GA4_METRICS]


def make_site_df() -> pd.DataFrame:
    data = [
        # data, activeUsers, newUsers, sessions, engagedSessions, views, engagement seconds
        ["20261010", "100", "40", "150", "90", "400", "5000.50"],
        ["20261011", "120", "50", "180", "100", "450", "5500.25"],
        ["20261012", "90", "30", "130", "70", "300", "4000"],
        ["2026-1", "1", "1", "1", "1", "1", "1"],  # data malformata: da scartare
    ]
    return pd.DataFrame(data, columns=SITE_COLS)


def make_channel_df(include_not_set: bool = True) -> pd.DataFrame:
    per_day = {
        "20261010": [("Organic Search", 100), ("Direct", 40), ("", 10)],
        "20261011": [("Organic Search", 120), ("Direct", 50), ("", 10)],
        "20261012": [("Organic Search", 80), ("Direct", 40), ("", 10)],
    }
    data = []
    for day, channels in per_day.items():
        for channel, s in channels:
            if channel == "" and not include_not_set:
                continue
            data.append([day, channel, str(s // 2), str(s // 4), str(s), str(s // 2), str(s * 3), f"{s * 30}.0"])
    return pd.DataFrame(data, columns=CHANNEL_COLS)


START, END = dt.date(2026, 10, 10), dt.date(2026, 10, 12)


def run(client, sources=("site", "channel", "period")):
    with _conn() as c:
        return ing.run_all(client, c, "123", START, END, TODAY, sources)


# ----------------------------------------------------------------------
# Test
# ----------------------------------------------------------------------
def test_migration_up() -> None:
    reset_db()
    _alembic("upgrade", "head")
    assert scalar("SELECT version_num FROM alembic_version") == "0004_ga4_site_tables"
    names = {r[0] for r in rows(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")}
    for t in ("fact_ga4_site_daily", "fact_ga4_channel_daily", "fact_ga4_site_period", "etl_run_log"):
        assert t in names, f"manca la tabella {t}"
    print("OK  1. migration UP: 4 tabelle create, alembic_version = 0004")


def test_constraints() -> None:
    expect_error(pg_errors.CheckViolation,
                 "INSERT INTO fact_ga4_site_daily (metric_date, sessions) VALUES ('2026-10-01', -1)")
    expect_error(pg_errors.CheckViolation,
                 "INSERT INTO fact_ga4_site_period (period_type, period_start, period_end, is_complete) "
                 "VALUES ('year', '2026-01-01', '2026-12-31', false)")
    expect_error(pg_errors.CheckViolation,
                 "INSERT INTO fact_ga4_site_period (period_type, period_start, period_end, is_complete) "
                 "VALUES ('week', '2026-10-12', '2026-10-06', false)")
    expect_error(pg_errors.CheckViolation,
                 "INSERT INTO etl_run_log (source, status) VALUES ('x', 'boh')")
    with _conn() as c, c.cursor() as cur:
        cur.execute("INSERT INTO fact_ga4_channel_daily (metric_date, channel_group) VALUES ('2026-10-01', 'Direct')")
    expect_error(pg_errors.UniqueViolation,
                 "INSERT INTO fact_ga4_channel_daily (metric_date, channel_group) VALUES ('2026-10-01', 'Direct')")
    with _conn() as c, c.cursor() as cur:  # nessun CHECK sui valori di channel_group
        cur.execute("INSERT INTO fact_ga4_channel_daily (metric_date, channel_group) VALUES ('2026-10-01', 'Canale Nuovo GA4')")
        cur.execute("DELETE FROM fact_ga4_channel_daily")
    print("OK  2. vincoli: negativi, vocabolari, intervallo, PK rifiutati; channel_group libero")


def test_pure_functions() -> None:
    ns = lambda **kw: Namespace(**{"days": None, "date": None, "start": None, "end": None, **kw})
    assert ing.resolve_range(ns(), TODAY) == (dt.date(2026, 10, 16), YESTERDAY)
    assert ing.resolve_range(ns(start="2025-08-01"), TODAY) == (dt.date(2025, 8, 1), YESTERDAY)
    assert ing.resolve_range(ns(date="2026-10-10"), TODAY) == (dt.date(2026, 10, 10),) * 2
    for bad in (ns(end="2026-10-10"), ns(start="2026-10-12", end="2026-10-10"),
                ns(start="2026-10-01", end="2026-10-25"), ns(start="2020-01-01")):
        try:
            ing.resolve_range(bad, TODAY)
        except ValueError:
            continue
        raise AssertionError(f"atteso ValueError per {bad}")

    weeks = list(ing.iter_weeks(dt.date(2026, 10, 3), dt.date(2026, 10, 12)))
    assert weeks == [
        (dt.date(2026, 9, 28), dt.date(2026, 10, 4)),
        (dt.date(2026, 10, 5), dt.date(2026, 10, 11)),
        (dt.date(2026, 10, 12), dt.date(2026, 10, 18)),
    ], weeks
    months = list(ing.iter_months(dt.date(2026, 9, 30), dt.date(2026, 10, 12)))
    assert months == [
        (dt.date(2026, 9, 1), dt.date(2026, 9, 30)),
        (dt.date(2026, 10, 1), dt.date(2026, 10, 31)),
    ], months
    assert list(ing.iter_months(dt.date(2026, 12, 15), dt.date(2027, 1, 5)))[-1] == (
        dt.date(2027, 1, 1), dt.date(2027, 1, 31))  # cambio d'anno
    assert len(ing.build_periods(START, END)) == 5
    print("OK  3. funzioni pure: range, settimane (lunedi-domenica), mesi, cambio d'anno")


def test_ingest_and_reconcile() -> None:
    client = FakeClient(make_site_df(), make_channel_df())
    results = run(client)
    assert results == {"site": True, "channel": True, "period": True}, results

    assert scalar("SELECT count(*) FROM fact_ga4_site_daily") == 3  # la data malformata e' scartata
    assert scalar("SELECT user_engagement_duration FROM fact_ga4_site_daily WHERE metric_date = '2026-10-10'") == 5000.50
    assert scalar("SELECT sessions FROM fact_ga4_site_daily WHERE metric_date = '2026-10-11'") == 180

    assert scalar("SELECT count(*) FROM fact_ga4_channel_daily") == 9
    assert scalar("SELECT count(*) FROM fact_ga4_channel_daily WHERE channel_group = '(not set)'") == 3

    # Riconciliazione: sessioni dei canali = sessioni del sito, per ogni giorno.
    mismatch = rows(
        """SELECT s.metric_date FROM fact_ga4_site_daily s
           JOIN fact_ga4_channel_daily c USING (metric_date)
           GROUP BY s.metric_date, s.sessions
           HAVING abs(sum(c.sessions) - s.sessions) > 0.01 * s.sessions""")
    assert mismatch == [], mismatch

    periods = {(r[0], r[1]): r[2:] for r in rows(
        "SELECT period_type, period_start, period_end, is_complete, active_users FROM fact_ga4_site_period")}
    assert len(periods) == 5
    assert periods[("week", dt.date(2026, 10, 12))][1] is True  # domenica 18 <= ieri
    assert periods[("month", dt.date(2026, 10, 1))][1] is False  # ottobre non e' finito
    assert periods[("month", dt.date(2026, 9, 1))][1] is True
    # La query del periodo in corso si ferma a ieri: mai richieste oltre.
    assert all(dt.date.fromisoformat(c["end"]) <= YESTERDAY for c in client.calls), client.calls
    # Nessuna dimensione data nelle query dei periodi.
    assert any(c["dimensions"] is None for c in client.calls)

    log = rows("SELECT source, status, rows_written FROM etl_run_log ORDER BY run_id")
    assert log == [("ga4_site_daily", "success", 3), ("ga4_channel_daily", "success", 9),
                   ("ga4_site_period", "success", 5)], log
    print("OK  4. ingestione: tipi, data scartata, '(not set)', riconciliazione canali, periodi, log")


def test_idempotent() -> None:
    first = scalar("SELECT fetched_at FROM fact_ga4_site_daily WHERE metric_date = '2026-10-10'")
    run(FakeClient(make_site_df(), make_channel_df()))
    assert scalar("SELECT count(*) FROM fact_ga4_site_daily") == 3
    assert scalar("SELECT count(*) FROM fact_ga4_channel_daily") == 9
    assert scalar("SELECT count(*) FROM fact_ga4_site_period") == 5
    assert scalar("SELECT fetched_at FROM fact_ga4_site_daily WHERE metric_date = '2026-10-10'") > first
    print("OK  5. idempotenza: nessun duplicato, fetched_at aggiornato")


def test_channel_replace_removes_orphans() -> None:
    run(FakeClient(make_site_df(), make_channel_df(include_not_set=False)), sources=("channel",))
    assert scalar("SELECT count(*) FROM fact_ga4_channel_daily WHERE channel_group = '(not set)'") == 0
    assert scalar("SELECT count(*) FROM fact_ga4_channel_daily") == 6
    print("OK  6. canali: un gruppo sparito in una revisione non resta orfano")


def test_empty_response_does_not_delete() -> None:
    empty = pd.DataFrame(columns=CHANNEL_COLS)
    results = run(FakeClient(make_site_df(), empty), sources=("channel",))
    assert results == {"channel": False}
    assert scalar("SELECT count(*) FROM fact_ga4_channel_daily") == 6  # nulla cancellato
    status, err = rows("SELECT status, error_message FROM etl_run_log WHERE source = 'ga4_channel_daily' "
                       "ORDER BY run_id DESC LIMIT 1")[0]
    assert status == "failed" and "0 righe" in err, (status, err)
    print("OK  7. risposta vuota: fonte fallita, nessun DELETE, errore nel log")


def test_auto_planning_from_db() -> None:
    import ingest_ga4 as art

    # Sito/canali: dopo i test precedenti ci sono i giorni 10-12 ottobre e 5 periodi.
    with _conn() as c:
        start, end, why = ing.plan_from_db(c, dt.date(2026, 10, 10), TODAY, 3)
    assert (start, end) == (dt.date(2026, 10, 13), YESTERDAY), (start, end)
    assert why["missing_days"] == 6 and why["stale_periods"] == 0, why

    # Articoli: due giorni presenti con un buco in mezzo (11 ottobre).
    with _conn() as c, c.cursor() as cur:
        cur.execute("INSERT INTO articles_dim (article_id, slug, link, title) "
                    "VALUES (1001, 'slug1', 'https://example.com/slug1/', 'Articolo 1')")
        for day in ("2026-10-10", "2026-10-12"):
            cur.execute("INSERT INTO fact_ga4_daily (article_id, metric_date, metric_name, metric_value) "
                        "VALUES (1001, %s, 'screen_page_views', 5)", (day,))
    with _conn() as c:
        days, deferred = art.plan_auto_days(c, dt.date(2026, 10, 9), TODAY, 3, 60)
    expected = [dt.date(2026, 10, d) for d in (9, 11, 13, 14, 15, 16, 17, 18)]
    assert days == expected and deferred == 0, (days, deferred)
    print("OK  8. pianificazione --auto dal DB: giorni mancanti, buco in mezzo e ultimi 3 giorni")


def test_migration_reversible() -> None:
    _alembic("downgrade", "-1")
    names = {r[0] for r in rows(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")}
    assert not names & {"fact_ga4_site_daily", "fact_ga4_channel_daily", "fact_ga4_site_period", "etl_run_log"}
    assert "fact_ga4_daily" in names  # le tabelle precedenti restano
    _alembic("upgrade", "head")
    assert scalar("SELECT version_num FROM alembic_version") == "0004_ga4_site_tables"
    print("OK  9. migration reversibile: DOWN poi UP")


def main() -> int:
    test_migration_up()
    test_constraints()
    test_pure_functions()
    test_ingest_and_reconcile()
    test_idempotent()
    test_channel_replace_removes_orphans()
    test_empty_response_does_not_delete()
    test_auto_planning_from_db()
    test_migration_reversible()
    print("\nTutti i test superati.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
