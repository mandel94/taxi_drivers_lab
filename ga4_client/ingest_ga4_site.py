"""
ingest_ga4_site.py

Ingestione GA4 dei totali di sito, dei canali e degli utenti su periodo:

  fonte            tabella                    grain                 scrittura
  ga4_site_daily   fact_ga4_site_daily        giorno                upsert
  ga4_channel_daily fact_ga4_channel_daily    giorno x canale       cancella e reinserisci
  ga4_site_period  fact_ga4_site_period       settimana / mese      upsert

Differenze rispetto a ingest_ga4.py (articoli):
  - Una sola query per l'intero intervallo (sito e canali), non una per giorno:
    il vincolo "una query per giorno" serve a evitare che pagePath faccia
    esplodere le righe, qui sono poche centinaia.
  - I canali sono riscritti con DELETE + INSERT in una sola transazione. Con il
    solo upsert, un gruppo che GA4 fa sparire o rinomina in una revisione
    resterebbe orfano e la somma dei canali non tornerebbe col totale del sito.
  - Gli utenti unici di settimana/mese non si ricavano dai giornalieri: GA4 e'
    interrogato con l'intervallo del periodo e senza dimensione data.
  - Ogni fonte scrive una riga in etl_run_log (running -> success / failed),
    in una transazione a parte, cosi' il log sopravvive a un rollback.

Dimensione canale: sessionDefaultChannelGroup (decisione fissata prima del
backfill: cambiarla dopo spezzerebbe lo storico).

Uso:
    export GA4_PROPERTY_ID=123456789
    export DATABASE_URL=postgresql://user:pass@localhost:5434/taxidrivers

    python ingest_ga4_site.py                          # ultimi 3 giorni (default)
    python ingest_ga4_site.py --days 7
    python ingest_ga4_site.py --start 2025-08-01 --end yesterday   # backfill
    python ingest_ga4_site.py --date 2026-10-10
    python ingest_ga4_site.py --only channel           # una sola fonte
    python ingest_ga4_site.py --auto --floor 2025-08-01  # backfill dinamico (usato dall'ETL)

--auto guarda cosa c'e' nel DB e carica da solo tutto quello che manca: giorni senza righe,
periodi mai caricati o rimasti incompleti dopo la loro fine, piu' gli ultimi --revise-days
giorni (default 3) che GA4 puo' ancora rivedere. Dopo un fermo recupera tutto alla prima
esecuzione utile. --floor e' il primo giorno atteso: prima non si cerca nulla.

Le date possono essere ISO (YYYY-MM-DD) o relative GA4 (yesterday, NdaysAgo).
Per i periodi vengono ricaricati anche la settimana e il mese precedenti
all'intervallo, perche' GA4 rivede i dati recenti.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from typing import Callable

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

from backfill_plan import iter_months, iter_weeks, plan_site_range
from etl_log import finish_run, start_run
from ga4_client import GA4Client
from ga4_service import parse_ga4_date
from ingest_ga4 import _resolve_date

DEFAULT_DAYS = 3
MAX_DAYS = 800

CHANNEL_DIMENSION = "sessionDefaultChannelGroup"
NOT_SET_LABEL = "(not set)"

# Nome GA4 (camelCase) -> colonna delle tabelle (snake_case). L'ordine e' quello
# delle colonne di fact_ga4_site_daily / fact_ga4_channel_daily.
METRIC_MAP = {
    "activeUsers": "active_users",
    "newUsers": "new_users",
    "sessions": "sessions",
    "engagedSessions": "engaged_sessions",
    "screenPageViews": "screen_page_views",
    "userEngagementDuration": "user_engagement_duration",
}
GA4_METRICS = list(METRIC_MAP)
VALUE_COLUMNS = list(METRIC_MAP.values())
INT_COLUMNS = VALUE_COLUMNS[:-1]
FLOAT_COLUMN = "user_engagement_duration"

SOURCE_NAMES = {
    "site": "ga4_site_daily",
    "channel": "ga4_channel_daily",
    "period": "ga4_site_period",
}

SITE_UPSERT_SQL = """
    INSERT INTO fact_ga4_site_daily
        (metric_date, active_users, new_users, sessions, engaged_sessions,
         screen_page_views, user_engagement_duration)
    VALUES %s
    ON CONFLICT (metric_date) DO UPDATE SET
        active_users = EXCLUDED.active_users,
        new_users = EXCLUDED.new_users,
        sessions = EXCLUDED.sessions,
        engaged_sessions = EXCLUDED.engaged_sessions,
        screen_page_views = EXCLUDED.screen_page_views,
        user_engagement_duration = EXCLUDED.user_engagement_duration,
        fetched_at = now()
"""

CHANNEL_DELETE_SQL = (
    "DELETE FROM fact_ga4_channel_daily WHERE metric_date BETWEEN %s AND %s"
)
CHANNEL_INSERT_SQL = """
    INSERT INTO fact_ga4_channel_daily
        (metric_date, channel_group, active_users, new_users, sessions,
         engaged_sessions, screen_page_views, user_engagement_duration)
    VALUES %s
"""

PERIOD_UPSERT_SQL = """
    INSERT INTO fact_ga4_site_period
        (period_type, period_start, period_end, active_users, new_users, is_complete)
    VALUES %s
    ON CONFLICT (period_type, period_start) DO UPDATE SET
        period_end = EXCLUDED.period_end,
        active_users = EXCLUDED.active_users,
        new_users = EXCLUDED.new_users,
        is_complete = EXCLUDED.is_complete,
        fetched_at = now()
"""


# ---------------------------------------------------------------------------
# Date e periodi
# ---------------------------------------------------------------------------


def resolve_range(args, today: dt.date) -> tuple[dt.date, dt.date]:
    """Risolve gli argomenti CLI in (start, end), estremi inclusi."""
    if args.date:
        start = end = _resolve_date(args.date, today)
    elif args.start:
        start = _resolve_date(args.start, today)
        end = _resolve_date(args.end or "yesterday", today)
    elif args.end:
        raise ValueError("--end richiede anche --start.")
    else:
        days = args.days or DEFAULT_DAYS
        if days < 1:
            raise ValueError("--days deve essere >= 1.")
        end = today - dt.timedelta(days=1)
        start = end - dt.timedelta(days=days - 1)

    if end < start:
        raise ValueError("il range e' invertito: --end precede --start.")
    if end > today:
        raise ValueError("--end non puo' essere nel futuro.")
    total = (end - start).days + 1
    if total > MAX_DAYS:
        raise ValueError(
            f"il range richiede {total} giorni (limite {MAX_DAYS}). Usa un range piu' corto."
        )
    return start, end


def plan_from_db(conn, floor: dt.date, today: dt.date, revise_days: int):
    """Modalita' --auto: guarda cosa c'e' davvero nel DB e calcola l'intervallo da caricare
    (giorni mancanti di sito o canali, periodi mancanti o rimasti incompleti, ultimi giorni
    rivisti da GA4). La logica vera e' in backfill_plan.plan_site_range."""
    yesterday = today - dt.timedelta(days=1)
    with conn.cursor() as cur:
        cur.execute("SELECT metric_date FROM fact_ga4_site_daily WHERE metric_date >= %s", (floor,))
        site = {r[0] for r in cur.fetchall()}
        cur.execute(
            "SELECT DISTINCT metric_date FROM fact_ga4_channel_daily WHERE metric_date >= %s",
            (floor,),
        )
        channel = {r[0] for r in cur.fetchall()}
        cur.execute(
            "SELECT period_type, period_start, is_complete FROM fact_ga4_site_period "
            "WHERE period_start >= %s",
            (floor,),
        )
        periods = {(t, s): complete for t, s, complete in cur.fetchall()}
    conn.rollback()  # solo letture: chiude la transazione implicita
    return plan_site_range(site, channel, periods, floor, yesterday, revise_days)


def build_periods(
    start: dt.date, end: dt.date
) -> list[tuple[str, dt.date, dt.date]]:
    """Periodi da (ri)caricare: quelli che toccano [start, end] piu' la
    settimana e il mese precedenti, perche' GA4 rivede i dati recenti."""
    periods = [
        ("week", ws, we) for ws, we in iter_weeks(start - dt.timedelta(days=7), end)
    ]
    month_from = start.replace(day=1) - dt.timedelta(days=1)
    periods += [("month", ms, me) for ms, me in iter_months(month_from, end)]
    return periods


# ---------------------------------------------------------------------------
# Lettura da GA4 e conversione in record
# ---------------------------------------------------------------------------


def _clean_frame(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Rinomina le metriche, valida la data (YYYYMMDD) e converte i tipi.
    run_query restituisce stringhe: vanno convertite prima di scrivere.
    Ritorna (df pulito, numero di righe scartate per data malformata)."""
    df = df.rename(columns=METRIC_MAP).copy()
    df["metric_date"] = df["date"].map(parse_ga4_date)
    bad = df["metric_date"].isna()
    discarded = int(bad.sum())
    df = df.loc[~bad].copy()
    for col in INT_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    df[FLOAT_COLUMN] = (
        pd.to_numeric(df[FLOAT_COLUMN], errors="coerce").fillna(0.0).round(2)
    )
    return df, discarded


def fetch_site_daily(client, property_id, start: dt.date, end: dt.date):
    """Una query per l'intero intervallo, dimensione 'date' e nient'altro."""
    df = client.run_query(
        property_id=property_id,
        metrics=GA4_METRICS,
        dimensions=["date"],
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )
    if df.empty:
        return [], 0
    df, discarded = _clean_frame(df)
    columns = ["metric_date", *VALUE_COLUMNS]
    rows = list(zip(*[df[c].tolist() for c in columns]))
    return rows, discarded


def fetch_channel_daily(client, property_id, start: dt.date, end: dt.date):
    """Una query per l'intero intervallo, dimensioni 'date' e canale."""
    df = client.run_query(
        property_id=property_id,
        metrics=GA4_METRICS,
        dimensions=["date", CHANNEL_DIMENSION],
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )
    if df.empty:
        return [], 0
    df, discarded = _clean_frame(df)
    df = df.rename(columns={CHANNEL_DIMENSION: "channel_group"})
    df["channel_group"] = (
        df["channel_group"].fillna("").astype(str).str.strip().replace("", NOT_SET_LABEL)
    )
    # Difensivo: la PK e' (metric_date, channel_group). Se la normalizzazione
    # dell'etichetta producesse un duplicato, si sommano le righe.
    df = df.groupby(["metric_date", "channel_group"], as_index=False)[VALUE_COLUMNS].sum()
    columns = ["metric_date", "channel_group", *VALUE_COLUMNS]
    rows = list(zip(*[df[c].tolist() for c in columns]))
    return rows, discarded


def fetch_period_users(client, property_id, start: dt.date, end: dt.date):
    """Utenti unici sull'intervallo del periodo, SENZA dimensione data.
    Ritorna (active_users, new_users) oppure None se GA4 non restituisce righe."""
    df = client.run_query(
        property_id=property_id,
        metrics=["activeUsers", "newUsers"],
        dimensions=None,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )
    if df.empty:
        return None
    row = df.iloc[0]
    active = int(pd.to_numeric(row["activeUsers"], errors="coerce") or 0)
    new = int(pd.to_numeric(row["newUsers"], errors="coerce") or 0)
    return active, new


# ---------------------------------------------------------------------------
# Scrittura
# ---------------------------------------------------------------------------


def upsert_site_daily(cur, rows) -> None:
    if rows:
        execute_values(cur, SITE_UPSERT_SQL, rows)


def replace_channel_daily(cur, start: dt.date, end: dt.date, rows) -> None:
    """Cancella e reinserisce l'intervallo nella stessa transazione: ogni
    giorno e' la fotografia dell'ultima risposta di GA4. Il commit lo fa il
    chiamante: se l'insert fallisce, il DELETE viene annullato."""
    cur.execute(CHANNEL_DELETE_SQL, (start, end))
    if rows:
        execute_values(cur, CHANNEL_INSERT_SQL, rows)


def upsert_periods(cur, rows) -> None:
    if rows:
        execute_values(cur, PERIOD_UPSERT_SQL, rows)


# ---------------------------------------------------------------------------
# etl_run_log
# ---------------------------------------------------------------------------


def run_job(conn, source, date_from, date_to, work: Callable[[], int]) -> bool:
    """Esegue una fonte con log. `work` fa il proprio commit e ritorna le
    righe scritte. Un errore in una fonte non ferma le altre."""
    run_id = start_run(conn, source, date_from, date_to)
    try:
        written = work()
    except Exception as exc:  # noqa: BLE001 - qualunque errore va loggato e segnalato
        conn.rollback()
        finish_run(conn, run_id, "failed", None, f"{type(exc).__name__}: {exc}")
        print(f"[{source}] ERRORE - {exc}", file=sys.stderr)
        return False
    finish_run(conn, run_id, "success", written)
    print(f"[{source}] ok - righe scritte: {written}")
    return True


# ---------------------------------------------------------------------------
# Orchestrazione
# ---------------------------------------------------------------------------


def run_all(
    client,
    conn,
    property_id,
    start: dt.date,
    end: dt.date,
    today: dt.date,
    sources=("site", "channel", "period"),
) -> dict[str, bool]:
    """Esegue le fonti richieste e ritorna {fonte: riuscita}."""
    yesterday = today - dt.timedelta(days=1)
    results: dict[str, bool] = {}

    def work_site() -> int:
        rows, discarded = fetch_site_daily(client, property_id, start, end)
        if discarded:
            print(f"[ga4_site_daily] {discarded} righe con data malformata scartate")
        if not rows:
            # GA4 non restituisce righe per il range: meglio segnalarlo che
            # dichiarare un successo vuoto.
            raise RuntimeError("GA4 ha restituito 0 righe: nessuna modifica scritta")
        with conn.cursor() as cur:
            upsert_site_daily(cur, rows)
        conn.commit()
        return len(rows)

    def work_channel() -> int:
        rows, discarded = fetch_channel_daily(client, property_id, start, end)
        if discarded:
            print(f"[ga4_channel_daily] {discarded} righe con data malformata scartate")
        if not rows:
            # Niente DELETE su una risposta vuota: cancelleremmo dati veri
            # per un problema temporaneo dell'API.
            raise RuntimeError("GA4 ha restituito 0 righe: nessuna modifica scritta")
        with conn.cursor() as cur:
            replace_channel_daily(cur, start, end, rows)
        conn.commit()
        return len(rows)

    def work_period() -> int:
        rows = []
        for period_type, p_start, p_end in build_periods(start, end):
            if p_start > yesterday:
                continue  # periodo che non e' ancora iniziato
            # GA4 non ha dati oltre ieri: la query si ferma li', il periodo
            # resta incompleto e verra' riscritto alla prossima esecuzione.
            users = fetch_period_users(client, property_id, p_start, min(p_end, yesterday))
            if users is None:
                continue
            rows.append(
                (period_type, p_start, p_end, users[0], users[1], p_end <= yesterday)
            )
        with conn.cursor() as cur:
            upsert_periods(cur, rows)
        conn.commit()
        return len(rows)

    jobs = {"site": work_site, "channel": work_channel, "period": work_period}
    for key in ("site", "channel", "period"):
        if key in sources:
            results[key] = run_job(conn, SOURCE_NAMES[key], start, end, jobs[key])
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingestione GA4 di sito, canali e utenti su periodo."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--days",
        type=int,
        default=None,
        help=f"ultimi N giorni fino a ieri (default {DEFAULT_DAYS}).",
    )
    group.add_argument("--date", default=None, help="un solo giorno (ISO o relativo GA4).")
    parser.add_argument("--start", default=None, help="data inizio (ISO o relativa GA4).")
    parser.add_argument("--end", default=None, help="data fine (default: yesterday).")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="calcola da solo l'intervallo da caricare (vedi sopra); richiede --floor.",
    )
    parser.add_argument("--floor", default=None, help="primo giorno atteso, con --auto.")
    parser.add_argument(
        "--revise-days",
        type=int,
        default=DEFAULT_DAYS,
        help=f"con --auto: ultimi N giorni sempre ricaricati (default {DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "--only",
        nargs="+",
        choices=sorted(SOURCE_NAMES),
        default=list(SOURCE_NAMES),
        help="limita l'esecuzione ad alcune fonti.",
    )
    parser.add_argument("--client-secrets", default="client_secrets.json")
    parser.add_argument("--token", default="token.json")
    args = parser.parse_args()

    property_id = os.environ.get("GA4_PROPERTY_ID")
    database_url = os.environ.get("DATABASE_URL")
    if not property_id:
        print("ERRORE: variabile d'ambiente GA4_PROPERTY_ID mancante.", file=sys.stderr)
        return 1
    if not database_url:
        print("ERRORE: variabile d'ambiente DATABASE_URL mancante.", file=sys.stderr)
        return 1

    today = dt.date.today()
    floor = start = end = None
    try:
        if args.auto:
            if args.days or args.date or args.start or args.end:
                raise ValueError("--auto non si combina con --days, --date, --start, --end.")
            if not args.floor:
                raise ValueError("--auto richiede --floor (primo giorno atteso).")
            floor = _resolve_date(args.floor, today)
        else:
            start, end = resolve_range(args, today)
            print(f"Range: {start} -> {end} ({(end - start).days + 1} giorni) | fonti: {', '.join(args.only)}\n")
    except ValueError as exc:
        print(f"ERRORE: {exc}", file=sys.stderr)
        return 2

    client = GA4Client(client_secrets_path=args.client_secrets, token_path=args.token)
    conn = psycopg2.connect(database_url.replace("postgresql+psycopg2://", "postgresql://"))
    try:
        if args.auto:
            plan = plan_from_db(conn, floor, today, args.revise_days)
            if plan is None:
                print(f"Niente da fare: --floor {floor} e' successivo a ieri.")
                return 0
            start, end, reasons = plan
            print(
                f"Auto: {start} -> {end} ({(end - start).days + 1} giorni) | fonti: {', '.join(args.only)}\n"
                f"  giorni mancanti: {reasons['missing_days']} | periodi da rinfrescare: "
                f"{reasons['stale_periods']} | giorni sempre ricaricati: {reasons['revise_days']}\n"
            )
        results = run_all(client, conn, property_id, start, end, today, args.only)
    finally:
        conn.close()

    failed = [SOURCE_NAMES[k] for k, ok in results.items() if not ok]
    print("\n--- Riepilogo ---")
    for key, ok in results.items():
        print(f"{SOURCE_NAMES[key]}: {'ok' if ok else 'FALLITA'}")
    if failed:
        print(f"ATTENZIONE: {len(failed)} fonte/i fallite (vedi etl_run_log).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
