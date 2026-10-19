"""
backfill_plan.py

Calcolo dinamico dei giorni da (ri)caricare, senza toccare il database: le funzioni ricevono
cio' che e' gia' presente e restituiscono cosa manca. Cosi' l'ETL giornaliero non dipende dal
fatto che ogni esecuzione sia andata a buon fine: dopo un fermo (PC spento, GA4 non
raggiungibile, un giorno fallito) la volta successiva recupera da sola tutto quello che manca.

Regole:
  - "floor" e' il primo giorno atteso: prima di quella data non si cerca nulla (nel DB possono
    esserci giorni isolati caricati per prova, che non sono copertura).
  - Si ricaricano sempre gli ultimi `revise_days` giorni, perche' GA4 rivede i dati recenti.
  - Un giorno e' "mancante" se non ha nessuna riga nella tabella.
  - Per gli articoli (una query GA4 per giorno) il recupero e' limitato a `max_missing` giorni
    per esecuzione, dal piu' vecchio: il resto viene riportato come "rinviato" e recuperato alle
    esecuzioni successive, cosi' un buco di mesi non blocca l'ETL ne' esaurisce la quota GA4.
  - Per sito e canali (una query per l'intero intervallo) basta un solo intervallo contiguo, che
    parte dal giorno mancante piu' vecchio.
  - Periodi (settimane e mesi): si rinfrescano quelli mancanti e quelli salvati come incompleti
    che nel frattempo sono terminati.
"""

from __future__ import annotations

import calendar
import datetime as dt
from typing import Iterable


def month_end(d: dt.date) -> dt.date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def iter_weeks(start: dt.date, end: dt.date):
    """(lunedi, domenica) di ogni settimana che si sovrappone a [start, end]."""
    monday = start - dt.timedelta(days=start.weekday())
    while monday <= end:
        yield monday, monday + dt.timedelta(days=6)
        monday += dt.timedelta(days=7)


def iter_months(start: dt.date, end: dt.date):
    """(primo, ultimo giorno) di ogni mese che si sovrappone a [start, end]."""
    first = start.replace(day=1)
    while first <= end:
        yield first, month_end(first)
        first = month_end(first) + dt.timedelta(days=1)


def _days(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def plan_article_days(
    existing: Iterable[dt.date],
    floor: dt.date,
    yesterday: dt.date,
    revise_days: int = 3,
    max_missing: int = 60,
) -> tuple[list[dt.date], int]:
    """Giorni da caricare per la fact per articolo.

    Ritorna (giorni ordinati, giorni mancanti rinviati alle prossime esecuzioni).
    """
    if floor > yesterday:
        return [], 0
    existing = set(existing)
    all_days = _days(floor, yesterday)
    revise = set(all_days[-revise_days:]) if revise_days > 0 else set()
    missing = [d for d in all_days if d not in existing and d not in revise]
    chosen = missing[:max_missing]
    deferred = len(missing) - len(chosen)
    return sorted(set(chosen) | revise), deferred


def plan_site_range(
    existing_site: Iterable[dt.date],
    existing_channel: Iterable[dt.date],
    existing_periods: dict[tuple[str, dt.date], bool],
    floor: dt.date,
    yesterday: dt.date,
    revise_days: int = 3,
) -> tuple[dt.date, dt.date, dict] | None:
    """Intervallo contiguo [start, yesterday] da caricare per sito, canali e periodi.

    existing_periods: {(period_type, period_start): is_complete} gia' presenti.
    Ritorna (start, end, motivi) oppure None se il floor e' nel futuro.
    """
    if floor > yesterday:
        return None
    existing_site = set(existing_site)
    existing_channel = set(existing_channel)

    start = max(floor, yesterday - dt.timedelta(days=max(revise_days, 1) - 1))
    missing_days = [
        d for d in _days(floor, yesterday)
        if d not in existing_site or d not in existing_channel
    ]
    if missing_days:
        start = min(start, missing_days[0])

    # Periodi attesi: quelli che iniziano nella finestra di copertura e sono gia' iniziati.
    expected = [("week", ws) for ws, _ in iter_weeks(floor, yesterday) if ws >= floor]
    expected += [("month", ms) for ms, _ in iter_months(floor, yesterday) if ms >= floor]
    period_end = {("week", ws): we for ws, we in iter_weeks(floor, yesterday)}
    period_end.update({("month", ms): me for ms, me in iter_months(floor, yesterday)})

    stale_periods = []
    for key in expected:
        if key not in existing_periods:
            stale_periods.append(key)                       # mai caricato
        elif not existing_periods[key] and period_end[key] <= yesterday:
            stale_periods.append(key)                       # salvato incompleto, ora terminato
    if stale_periods:
        start = min(start, min(p_start for _, p_start in stale_periods))

    reasons = {
        "missing_days": len(missing_days),
        "stale_periods": len(stale_periods),
        "revise_days": revise_days,
    }
    return start, yesterday, reasons
