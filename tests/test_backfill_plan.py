"""
tests/test_backfill_plan.py

Test della logica pura del backfill dinamico (ga4_client/backfill_plan.py): nessun database,
nessuna chiamata a GA4. Verifica che dopo un fermo l'ETL recuperi da solo tutto quello che manca.

Esecuzione (dalla root del repo):
    .venv/Scripts/python.exe tests/test_backfill_plan.py
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ga4_client"))

from backfill_plan import plan_article_days, plan_site_range  # noqa: E402

D = dt.date
Y = D(2026, 10, 18)  # "ieri" (una domenica)


def span(a: dt.date, b: dt.date) -> list[dt.date]:
    return [a + dt.timedelta(days=i) for i in range((b - a).days + 1)]


def test_nothing_missing_reloads_only_recent_days() -> None:
    days, deferred = plan_article_days(span(D(2026, 10, 1), Y), D(2026, 10, 1), Y)
    assert days == span(D(2026, 10, 16), Y) and deferred == 0, days
    print("OK  1. nulla di mancante: solo gli ultimi 3 giorni (revisione GA4)")


def test_recovers_after_downtime() -> None:
    # La pipeline si e' fermata l'8 ottobre: giorni 9..15 mancanti, 16..18 da rivedere.
    days, deferred = plan_article_days(span(D(2026, 10, 1), D(2026, 10, 8)), D(2026, 10, 1), Y)
    assert days == span(D(2026, 10, 9), Y) and deferred == 0, days
    print("OK  2. dopo un fermo di 10 giorni recupera tutti i giorni mancanti")


def test_recovers_internal_gap() -> None:
    existing = [d for d in span(D(2026, 10, 1), Y) if d != D(2026, 10, 5)]
    days, _ = plan_article_days(existing, D(2026, 10, 1), Y)
    assert D(2026, 10, 5) in days and len(days) == 4, days  # il buco + 3 giorni rivisti
    print("OK  3. recupera anche un buco in mezzo alla copertura")


def test_cap_per_run_oldest_first() -> None:
    days, deferred = plan_article_days([], D(2026, 1, 1), Y, revise_days=3, max_missing=60)
    assert len(days) == 63 and days[0] == D(2026, 1, 1) and days[59] == D(2026, 3, 1), (len(days), days[0])
    assert days[-3:] == span(D(2026, 10, 16), Y), "gli ultimi giorni si ricaricano sempre"
    assert deferred == 288 - 60, deferred  # 291 giorni - 3 rivisti - 60 scelti
    # Esecuzioni successive: il rinviato si recupera a blocchi, nulla si perde.
    existing = set(days)
    nxt, deferred2 = plan_article_days(existing, D(2026, 1, 1), Y, 3, 60)
    assert nxt[0] == D(2026, 3, 2) and deferred2 == deferred - 60, (nxt[0], deferred2)
    print("OK  4. tetto per esecuzione: dal piu' vecchio, il resto rinviato e recuperato dopo")


def test_floor_and_edge_cases() -> None:
    assert plan_article_days([], D(2026, 10, 19), Y) == ([], 0)
    assert plan_article_days(span(D(2026, 10, 1), Y), D(2026, 10, 1), Y, revise_days=0) == ([], 0)
    # Un giorno isolato precedente al floor (caricato per prova) non conta come copertura
    # e non fa cercare giorni prima del floor.
    days, _ = plan_article_days([D(2025, 1, 15)], D(2026, 10, 15), Y)
    assert days == span(D(2026, 10, 15), Y), days
    print("OK  5. floor nel futuro, nessuna revisione, giorni isolati prima del floor ignorati")


def full_periods(upto: dt.date, floor: dt.date = D(2026, 10, 1)) -> dict:
    """Periodi gia' caricati e completi, per i test sul sito."""
    from backfill_plan import iter_months, iter_weeks
    out = {("week", ws): we <= upto for ws, we in iter_weeks(floor, upto) if ws >= floor}
    out.update({("month", ms): me <= upto for ms, me in iter_months(floor, upto) if ms >= floor})
    return out


def test_site_range() -> None:
    floor = D(2026, 10, 1)
    site = span(floor, Y)
    start, end, why = plan_site_range(site, site, full_periods(Y), floor, Y)
    assert (start, end) == (D(2026, 10, 16), Y) and why["missing_days"] == 0, (start, why)
    print("OK  6. sito/canali completi: solo gli ultimi 3 giorni")

    channel = [d for d in site if d != D(2026, 10, 5)]
    start, _, why = plan_site_range(site, channel, full_periods(Y), floor, Y)
    assert start == D(2026, 10, 5) and why["missing_days"] == 1, (start, why)
    print("OK  7. un giorno mancante solo nei canali: l'intervallo parte da li'")

    periods = full_periods(Y)
    periods[("week", D(2026, 10, 5))] = False  # salvata incompleta, ma ormai terminata
    start, _, why = plan_site_range(site, site, periods, floor, Y)
    assert start == D(2026, 10, 5) and why["stale_periods"] == 1, (start, why)
    print("OK  8. periodo salvato incompleto e nel frattempo terminato: viene rinfrescato")

    del periods[("week", D(2026, 10, 5))]  # mai caricato
    start, _, why = plan_site_range(site, site, periods, floor, Y)
    assert start == D(2026, 10, 5) and why["stale_periods"] == 1
    print("OK  9. periodo mai caricato: viene caricato")

    y2 = D(2026, 10, 16)  # venerdi: la settimana 12-18 e il mese sono ancora in corso
    site2 = span(floor, y2)
    periods2 = full_periods(y2)  # in corso => is_complete False
    start, _, why = plan_site_range(site2, site2, periods2, floor, y2)
    assert start == D(2026, 10, 14) and why["stale_periods"] == 0, (start, why)
    print("OK 10. un periodo ancora in corso non e' considerato da rinfrescare per forza")

    assert plan_site_range([], [], {}, D(2026, 10, 19), Y) is None
    print("OK 11. floor nel futuro: niente da fare")


def main() -> int:
    test_nothing_missing_reloads_only_recent_days()
    test_recovers_after_downtime()
    test_recovers_internal_gap()
    test_cap_per_run_oldest_first()
    test_floor_and_edge_cases()
    test_site_range()
    print("\nTutti i test superati.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
