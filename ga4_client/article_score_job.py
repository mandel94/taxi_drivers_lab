"""
article_score_job.py

Job di ingestion dello score editoriale per settimana (fact_article_score_period).

Per ogni settimana completa (lunedi-domenica):
  1. una query GA4 con dimensione pagePath e le metriche di GA4_METRICS sull'intervallo
     della settimana (utenti unici inclusi: non sono sommabili dai giornalieri);
  2. risolve ogni pagePath in article_id con la stessa regola di fact_ga4_daily
     (ga4_service.resolve_page_path: prefisso numerico del permalink, poi slug);
     le pagine non risolte (home, categorie, id non in articles_dim) vengono scartate
     prima dello scoring, cosi' lo score e' relativo solo agli articoli;
  3. aggrega le varianti di URL dello stesso articolo (combine_pages_by_article);
  4. calcola score, rank e segmento (article_scoring.score_articles);
  5. scrive con upsert idempotente, registrando il run in etl_run_log.

Modalita':
    python article_score_job.py --auto --floor 2026-08-16    # settimane complete mancanti
    python article_score_job.py --start 2026-08-17 --end 2026-10-18   # range (ricalcola)
    python article_score_job.py --week 2026-10-12            # una settimana (lunedi)

--auto guarda il DB e carica solo le settimane complete, dal floor in poi, che non hanno
ancora righe per METHOD_VERSION. Una settimana che fallisce non ferma le altre: il fallimento
e' nel log e l'exit code e' 1.

Uso (dalla cartella ga4_client, come i job GA4 del Makefile):
    export GA4_PROPERTY_ID=394327334
    export DATABASE_URL=postgresql://user:pass@localhost:5434/taxidrivers
    python article_score_job.py --auto --floor 2026-08-16
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys

import pandas as pd
import psycopg2

from article_score_writer import write_article_scores
from article_scoring import (
    GA4_METRICS,
    METHOD_VERSION,
    combine_pages_by_article,
    score_articles,
)
from backfill_plan import iter_weeks
from ga4_service import load_resolution_maps, resolve_page_path

PAGE_PATH_COLUMN = "pagePath"


def complete_weeks(start: dt.date, end: dt.date) -> list[tuple[dt.date, dt.date]]:
    """Settimane (lunedi, domenica) interamente contenute in [start, end]."""
    weeks = []
    for monday, sunday in iter_weeks(start, end):
        if monday >= start and sunday <= end:
            weeks.append((monday, sunday))
    return weeks


def missing_weeks(conn, weeks: list[tuple[dt.date, dt.date]]) -> list[tuple[dt.date, dt.date]]:
    """Le settimane che non hanno ancora righe per METHOD_VERSION."""
    if not weeks:
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT period_start, period_end FROM fact_article_score_period "
            "WHERE method_version = %s AND period_start >= %s AND period_end <= %s",
            (METHOD_VERSION, weeks[0][0], weeks[-1][1]),
        )
        present = {(s, e) for s, e in cur.fetchall()}
    return [w for w in weeks if w not in present]


def fetch_week_pages(client, property_id: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Una riga per pagePath con le metriche GA4 dell'intervallo."""
    return client.run_query(
        property_id=property_id,
        metrics=GA4_METRICS,
        dimensions=[PAGE_PATH_COLUMN],
        start_date=start.isoformat(),
        end_date=end.isoformat(),
    )


def attach_article_ids(conn, pages: pd.DataFrame) -> pd.DataFrame:
    """Aggiunge article_id alle pagine risolte e scarta le altre."""
    if pages.empty:
        return pages.assign(article_id=pd.Series(dtype="Int64"))

    with conn.cursor() as cur:
        slug_map, article_id_set = load_resolution_maps(cur)

    resolved = pages.assign(
        article_id=pages[PAGE_PATH_COLUMN].map(
            lambda p: resolve_page_path(p, slug_map, article_id_set)
        )
    )
    return resolved.dropna(subset=["article_id"]).assign(article_id=lambda d: d["article_id"].astype(int))


def run_week(conn, client, property_id: str, monday: dt.date, sunday: dt.date) -> dict:
    """Scarica, risolve, scora e scrive una settimana."""
    pages = fetch_week_pages(client, property_id, monday, sunday)
    articles = combine_pages_by_article(attach_article_ids(conn, pages))
    scored = score_articles(articles)
    return write_article_scores(conn, scored, monday, sunday, METHOD_VERSION)


def run(conn, client, property_id: str, weeks: list[tuple[dt.date, dt.date]]) -> bool:
    """Esegue le settimane in sequenza. Ritorna False se almeno una e' fallita."""
    ok = True
    for monday, sunday in weeks:
        try:
            run_week(conn, client, property_id, monday, sunday)
        except Exception as exc:  # noqa: BLE001 - una settimana non ferma le altre
            ok = False
            print(f"[article_score_period] {monday}..{sunday} ERRORE - {exc}", file=sys.stderr)
    return ok


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--auto", action="store_true", help="settimane complete mancanti dal floor")
    mode.add_argument("--start", type=dt.date.fromisoformat, help="inizio range (YYYY-MM-DD)")
    mode.add_argument("--week", type=dt.date.fromisoformat, help="lunedi di una settimana")
    parser.add_argument("--end", type=dt.date.fromisoformat, help="fine range (YYYY-MM-DD), con --start")
    parser.add_argument("--floor", type=dt.date.fromisoformat, help="primo giorno atteso, con --auto")
    args = parser.parse_args(argv)
    if args.start and not args.end:
        parser.error("--start richiede --end")
    if args.auto and not args.floor:
        parser.error("--auto richiede --floor")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    database_url = os.environ.get("DATABASE_URL")
    property_id = os.environ.get("GA4_PROPERTY_ID")
    if not database_url or not property_id:
        print("Imposta DATABASE_URL e GA4_PROPERTY_ID", file=sys.stderr)
        return 2

    yesterday = dt.date.today() - dt.timedelta(days=1)
    if args.auto:
        candidates = complete_weeks(args.floor, yesterday)
    elif args.week:
        candidates = complete_weeks(args.week, args.week + dt.timedelta(days=6))
    else:
        candidates = complete_weeks(args.start, min(args.end, yesterday))

    conn = psycopg2.connect(database_url.replace("postgresql+psycopg2://", "postgresql://"))
    try:
        weeks = missing_weeks(conn, candidates) if args.auto else candidates
        if not weeks:
            print("[article_score_period] nessuna settimana da caricare")
            return 0

        from ga4_client import GA4Client  # import tardivo: serve solo alle run reali

        client = GA4Client()
        ok = run(conn, client, property_id, weeks)
    finally:
        conn.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
