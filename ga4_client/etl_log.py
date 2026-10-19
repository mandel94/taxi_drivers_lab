"""
etl_log.py

Scrittura su etl_run_log, condivisa dagli script di ingestione. Ogni esecuzione di una fonte
lascia una riga: 'running' all'avvio, poi 'success' o 'failed'. Una riga rimasta 'running'
indica un job interrotto. La tabella alimenta mart_data_health.
"""

from __future__ import annotations

import datetime as dt


def start_run(conn, source: str, date_from: dt.date | None, date_to: dt.date | None) -> int:
    """Registra l'avvio in una transazione propria, cosi' il log sopravvive a un rollback del
    lavoro vero."""
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO etl_run_log (source, date_from, date_to) "
            "VALUES (%s, %s, %s) RETURNING run_id",
            (source, date_from, date_to),
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def finish_run(conn, run_id: int, status: str, rows_written, error: str | None = None) -> None:
    conn.rollback()  # stato pulito anche dopo un errore a meta' transazione
    message = error[:2000] if error else None
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE etl_run_log SET finished_at = now(), status = %s, "
            "rows_written = %s, error_message = %s WHERE run_id = %s",
            (status, rows_written, message, run_id),
        )
    conn.commit()
