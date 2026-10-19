"""
ingest_ga4.py

Entry point di ingestion GA4 -> fact_ga4_daily (formato long).

Risolve i page_path GA4 in article_id sfruttando il prefisso numerico
del permalink di taxidrivers.it (/<article_id>/<categoria>/<slug>.html),
con fallback sul match dello slug quando il prefisso manca, e pivota le
metriche in formato wide->long scrivendo con upsert
(ON CONFLICT (article_id, metric_date, metric_name) DO UPDATE).

Differenza rispetto alla versione pre-giornaliera: l'ingestion avviene
UNA QUERY PER GIORNO. Il range richiesto viene espanso in una lista di
date singole e per ciascuna viene interrogata la GA4 Data API con
start_date = end_date = quel giorno. Un unico commit a fine giorno:
un errore su un giorno non compromette i giorni gia' committati.

Uso:
    export GA4_PROPERTY_ID=123456789
    export DATABASE_URL=postgresql://user:pass@localhost:5434/taxidrivers

    python ingest_ga4.py                         # ultimi 30 giorni (default)
    python ingest_ga4.py --days 7                # ultimi 7 giorni
    python ingest_ga4.py --start 2026-08-15 --end 2026-08-25
    python ingest_ga4.py --date 2026-08-20       # un solo giorno
    python ingest_ga4.py --auto --floor 2026-08-16   # backfill dinamico (usato dall'ETL)

--auto guarda quali giorni da --floor a ieri non hanno nessuna riga in fact_ga4_daily e carica
quelli, piu' gli ultimi --revise-days giorni (default 3) che GA4 puo' ancora rivedere. Per non
esaurire la quota GA4 recupera al massimo --max-auto-days giorni mancanti per esecuzione, dal
piu' vecchio: il resto viene recuperato alle esecuzioni successive.

Codice di uscita: 0 se tutti i giorni sono andati a buon fine, 1 se almeno uno e' fallito.

Le date possono essere ISO (YYYY-MM-DD) o sintassi relativa GA4
(7daysAgo, yesterday). Il default e' --days 30 (da yesterday a 30
giorni prima inclusi).

Le credenziali OAuth (client_secrets.json / token.json) sono lette
dalla cartella corrente per default.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import psycopg2

from backfill_plan import plan_article_days
from etl_log import finish_run, start_run
from ga4_client import GA4Client
from ga4_service import (
    load_resolution_maps,
    resolve_article_ids,
    missing_article_ids,
    aggregate_by_article,
    to_long_format,
    long_records,
    upsert_records,
)

DEFAULT_DAYS = 30
MAX_DAYS = 400
DEFAULT_REVISE_DAYS = 3
DEFAULT_MAX_AUTO_DAYS = 60


def _resolve_date(raw: str, today: dt.date) -> dt.date:
    """Converte un argomento data in un dt.date concreto.

    Supporta ISO (YYYY-MM-DD) e sintassi relative GA4: today,
    yesterday, NdaysAgo (es. 7daysAgo).
    """
    s = raw.strip()
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        pass

    if s == "today":
        return today
    if s == "yesterday":
        return today - dt.timedelta(days=1)

    if s.endswith("daysAgo"):
        try:
            n = int(s[: -len("daysAgo")])
            return today - dt.timedelta(days=n)
        except ValueError:
            pass

    raise ValueError(
        f"data non riconosciuta: '{raw}'. Usa ISO (YYYY-MM-DD) oppure "
        "relative GA4 (today, yesterday, NdaysAgo)."
    )


def expand_days(args, today: dt.date) -> list[dt.date]:
    """Risolve l'argomento CLI in una lista esplicita di giorni singoli."""
    if args.date:
        start = _resolve_date(args.date, today)
        return [start]

    if args.start and args.end:
        start = _resolve_date(args.start, today)
        end = _resolve_date(args.end, today)
    elif args.start:
        start = _resolve_date(args.start, today)
        end = _resolve_date("yesterday", today)
    elif args.end:
        end = _resolve_date(args.end, today)
        start = _resolve_date("yesterday", today)
    else:
        days = args.days or DEFAULT_DAYS
        if days < 1:
            raise ValueError("--days deve essere >= 1 (usa --start/--end per range espliciti).")
        end = _resolve_date("yesterday", today)
        start = end - dt.timedelta(days=days - 1)

    if end < start:
        raise ValueError("il range e' invertito: --end precede --start.")

    total = (end - start).days + 1
    if total > MAX_DAYS:
        raise ValueError(
            f"il range richiede {total} giorni (limite {MAX_DAYS}). "
            "Usa un range piu' corto."
        )

    return [start + dt.timedelta(days=i) for i in range(total)]


def ingest_single_day(client, conn, property_id, slug_map, article_id_set, day) -> dict:
    """Esegue la query GA4 per il singolo giorno e scrive in fact_ga4_daily
    con un commit dedicato. Ritorna i conteggi per il log."""
    with conn.cursor() as cur:
        df = client.run_report(
            property_id=property_id,
            start_date=day.isoformat(),
            end_date=day.isoformat(),
        )

        matched, unmatched_paths = resolve_article_ids(df, slug_map, article_id_set)
        matched = aggregate_by_article(matched)
        long_df = to_long_format(matched)
        records = long_records(long_df)

        upsert_records(cur, records)
        conn.commit()

    return {
        "ga4_rows": len(df),
        "matched_rows": len(matched),
        "written": len(records),
        "unmatched": len(unmatched_paths),
        "missing_ids": missing_article_ids(unmatched_paths, article_id_set),
    }


def plan_auto_days(conn, floor: dt.date, today: dt.date, revise_days: int, max_missing: int):
    """Modalita' --auto: legge dal DB i giorni gia' presenti e ne ricava quelli da caricare.
    La logica vera e' in backfill_plan.plan_article_days."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT metric_date FROM fact_ga4_daily WHERE metric_date >= %s", (floor,))
        existing = {r[0] for r in cur.fetchall()}
    conn.rollback()  # solo lettura: chiude la transazione implicita
    return plan_article_days(
        existing, floor, today - dt.timedelta(days=1), revise_days, max_missing
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingestion GA4 giornaliera -> fact_ga4_daily (una query per giorno)."
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
    parser.add_argument("--end", default=None, help="data fine (ISO o relativa GA4).")
    parser.add_argument(
        "--auto",
        action="store_true",
        help="calcola da solo i giorni da caricare (vedi sopra); richiede --floor.",
    )
    parser.add_argument("--floor", default=None, help="primo giorno atteso, con --auto.")
    parser.add_argument(
        "--revise-days",
        type=int,
        default=DEFAULT_REVISE_DAYS,
        help=f"con --auto: ultimi N giorni sempre ricaricati (default {DEFAULT_REVISE_DAYS}).",
    )
    parser.add_argument(
        "--max-auto-days",
        type=int,
        default=DEFAULT_MAX_AUTO_DAYS,
        help=f"con --auto: giorni mancanti recuperati per esecuzione (default {DEFAULT_MAX_AUTO_DAYS}).",
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
    days = None
    floor = None
    try:
        if args.auto:
            if args.days or args.date or args.start or args.end:
                raise ValueError("--auto non si combina con --days, --date, --start, --end.")
            if not args.floor:
                raise ValueError("--auto richiede --floor (primo giorno atteso).")
            floor = _resolve_date(args.floor, today)
        else:
            days = expand_days(args, today)
            print(f"Range da ingerire: {days[0]} -> {days[-1]} ({len(days)} giorni)\n")
    except ValueError as exc:
        print(f"ERRORE: {exc}", file=sys.stderr)
        return 2

    client = GA4Client(client_secrets_path=args.client_secrets, token_path=args.token)

    conn = psycopg2.connect(database_url)
    exit_code = 0
    try:
        if args.auto:
            days, deferred = plan_auto_days(
                conn, floor, today, args.revise_days, args.max_auto_days
            )
            print(
                f"Auto: {len(days)} giorni da caricare"
                + (f" ({days[0]} -> {days[-1]})" if days else "")
                + f" | rinviati alle prossime esecuzioni: {deferred}\n"
            )
            if not days:
                print("Niente da fare: --floor e' successivo a ieri.")
                return 0
        run_id = start_run(conn, "ga4_articles", days[0], days[-1])
        with conn.cursor() as cur:
            slug_map, article_id_set = load_resolution_maps(cur)
        print(f"Articoli in articles_dim: {len(article_id_set)} (map slug: {len(slug_map)})\n")

        total_written = 0
        total_matched = 0
        total_unmatched = 0
        all_missing_ids: set[int] = set()
        failures = 0

        for i, day in enumerate(days, start=1):
            day_label = day.isoformat()
            try:
                counts = ingest_single_day(
                    client, conn, property_id, slug_map, article_id_set, day
                )
            except Exception as exc:
                conn.rollback()
                failures += 1
                print(
                    f"[giorno {i:>2}/{len(days)}] {day_label}: ERRORE - {exc}",
                    file=sys.stderr,
                )
                continue

            total_written += counts["written"]
            total_matched += counts["matched_rows"]
            total_unmatched += counts["unmatched"]
            all_missing_ids |= counts["missing_ids"]
            print(
                f"[giorno {i:>2}/{len(days)}] {day_label}: "
                f"righe GA4={counts['ga4_rows']:>4} | "
                f"match={counts['matched_rows']:>4} | "
                f"scritte={counts['written']:>5} | "
                f"non risolti={counts['unmatched']:>3}"
            )

        print("\n--- Riepilogo ---")
        print(f"Giorni eseguiti: {len(days) - failures}/{len(days)}")
        print(f"Righe GA4 totali con match: {total_matched}")
        print(f"Righe scritte in fact_ga4_daily: {total_written}")
        print(f"Page path non risolti (pagine non-articolo): {total_unmatched}")

        if all_missing_ids:
            max_known = max(article_id_set)
            recent = sorted(i for i in all_missing_ids if i > max_known)
            historical = sorted(i for i in all_missing_ids if i <= max_known)

            if recent:
                preview = ", ".join(str(i) for i in recent[:15])
                more = "" if len(recent) <= 15 else f" ... (+{len(recent) - 15})"
                print(
                    f"\nATTENZIONE: {len(recent)} articoli presenti in GA4 ma assenti "
                    "in articles_dim (pubblicati dopo l'ultima sync articoli)."
                )
                print(f"  id: {preview}{more}")
                print(
                    "  Per includerli: esegui 'make ingest-recent' e poi rilancia "
                    "l'ingestion GA4."
                )

            if historical:
                print(
                    f"\nNota: {len(historical)} prefissi numerici residui senza match "
                    f"(id <= {max_known}) non sono articoli ingeribili: corrispondono a "
                    "post WP non piu' disponibili o pagine con id numerico (es. /404)."
                )

        if failures:
            print(f"ATTENZIONE: {failures} giorno/i falliti (vedi log sopra).", file=sys.stderr)
            exit_code = 1
        finish_run(
            conn,
            run_id,
            "failed" if failures else "success",
            total_written,
            f"{failures} giorni falliti su {len(days)}" if failures else None,
        )
    finally:
        conn.close()

    return exit_code


if __name__ == "__main__":
    sys.exit(main())