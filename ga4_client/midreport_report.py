"""
ga4_client/midreport_report.py

Funzioni pure per il midreport (contratto: nlp/midreport_style/CONTRATTO.md).
Nessun DB, nessun GA4, nessuna rete.
"""

from __future__ import annotations

import datetime as dt
import html as _html

import pandas as pd
from openpyxl import Workbook
from openpyxl.worksheet.table import Table

from midreport_client import HEADERS, is_excluded_title  # noqa: F401

CATEGORY_ORDER = [
    "Si farà", "Serie TV", "Live Streaming On Demand", "News",
    "Festival di Cinema", "Speciali e Magazine", "Interviste",
    "Recensioni", "Anticipazioni", "Trailers",
]

INCIDENT_FROM = dt.date(2026, 11, 10)

_MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu",
           "lug", "ago", "set", "ott", "nov", "dic"]

_XLSX_COLUMNS = [
    "title", "editorial_score", "publication_date", "author",
    "category", "activeUsers", "engagementRate", "averageSessionDuration",
]


def week_label(start, end) -> str:
    if (start.year, start.month) == (end.year, end.month):
        return f"{start.day}-{end.day} {_MONTHS[end.month - 1]} {end.year}"
    return (f"{start.day} {_MONTHS[start.month - 1]} - "
            f"{end.day} {_MONTHS[end.month - 1]} {end.year}")


def date_ranges(start, end, exclude=()):
    """Intervalli contigui di giorni tra start e end, saltando i giorni esclusi."""
    skip = set(exclude)
    ranges, cur, day = [], None, start
    while day <= end:
        if day in skip:
            if cur:
                ranges.append(cur)
            cur = None
        else:
            cur = (cur[0], day) if cur else (day, day)
        day += dt.timedelta(days=1)
    if cur:
        ranges.append(cur)
    return ranges


def period_label(start, end, exclude=()) -> str:
    if not exclude:
        return week_label(start, end)
    ranges = date_ranges(start, end, exclude)
    multi_month = (start.year, start.month) != (end.year, end.month)
    parts = []
    for a, b in ranges:
        txt = str(a.day) if a == b else f"{a.day}-{b.day}"
        if multi_month:
            txt += f" {_MONTHS[b.month - 1]}"
        parts.append(txt)
    label = " e ".join(parts)
    if not multi_month:
        label += f" {_MONTHS[end.month - 1]}"
    return f"{label} {end.year}"


def subject(start, end, exclude=()) -> str:
    return (f"TaxiDrivers Analytics: Midreport Settimana "
            f"{start.isocalendar()[1]} ({period_label(start, end, exclude)})")


def drop_suspect(df):
    """Toglie il traffico sospetto: stessa regola della KB (engagement < 5%, durata < 3 s, almeno 20 utenti)."""
    bot = ((df["engagementRate"] < 0.05) & (df["averageSessionDuration"] < 3)
           & (df["activeUsers"] >= 20))
    return df[~bot].reset_index(drop=True)


def _valid(df):
    return df[~df["title"].map(is_excluded_title)]


def build_sections(df, per_cat=3):
    df = _valid(df)
    sections = {}
    for cat in CATEGORY_ORDER:
        sub = df[df["category"] == cat].sort_values(
            "editorial_score", ascending=False, kind="mergesort")
        rows = sub.head(per_cat).to_dict("records")
        if rows:
            sections[cat] = rows
    return sections


def build_notes(df, sections, min_users=50):
    df = _valid(df)
    notes = {}
    for cat in CATEGORY_ORDER:
        sub = df[df["category"] == cat]
        if sub.empty:
            continue
        top = sub.sort_values("activeUsers", ascending=False, kind="mergesort").iloc[0].to_dict()
        in_section = {r["title"] for r in sections.get(cat, [])}
        if top["title"] not in in_section and top["activeUsers"] >= min_users:
            notes[cat] = top
    return notes


def category_stats(df):
    df = _valid(df)
    users = df.groupby("category")["activeUsers"].sum()
    return (users / users.sum() * 100).to_dict()


def _int(x) -> int:
    return int(round(float(x)))


def format_item(row) -> str:
    return (f"'{row['title']}' (score: {_int(row['editorial_score'])}) → "
            f"{_int(row['activeUsers'])} utenti attivi, "
            f"{_int(row['engagementRate'] * 100)}% engagement, "
            f"{_int(row['averageSessionDuration'])}s.")


def format_note(row) -> str:
    return (f"Nota: '{row['title']}' (score: {_int(row['editorial_score'])}, "
            f"{_int(row['activeUsers'])} utenti attivi) → "
            f"{_int(row['engagementRate'] * 100)}% engagement, "
            f"{_int(row['averageSessionDuration'])}s.")


def _esc(text) -> str:
    return _html.escape(str(text))


def render_html(start, end, sintesi, sections, notes, chart_sentence, contesto_note=None, span=None,
                note_dati=None, chart_src=None):
    contesto_note = contesto_note or {}
    p = '<p style="margin:0 0 12px 0;font-family:Arial,sans-serif;font-size:14px;">'
    if span:
        pass
    elif (start.year, start.month) == (end.year, end.month):
        span = f"dal {start.day} al {end.day} {_MONTHS[end.month - 1]}"
    else:
        span = (f"dal {start.day} {_MONTHS[start.month - 1]} "
                f"al {end.day} {_MONTHS[end.month - 1]}")
    parts = [
        f"{p}Ciao Sandra, ciao Vincenzo, ciao Gianluca,</p>",
        f"{p}vi mando il midreport per la settimana {start.isocalendar()[1]} ({span}).</p>",
        f"{p}In sintesi:</p>",
        "<ul>",
    ]
    parts += [f"<li>{_esc(s)}</li>" for s in sintesi]
    parts.append("</ul>")
    if note_dati:
        parts.append(f"{p}<i>Nota sui dati: {_esc(note_dati)}</i></p>")
    for cat, rows in sections.items():
        parts.append(f"{p}<b>{_esc(cat)}:</b></p>")
        for r in rows:
            parts.append(f"{p}• <i>{_esc(r['title'])}</i> (score: {_int(r['editorial_score'])}) → "
                         f"{_int(r['activeUsers'])} utenti attivi, "
                         f"{_int(r['engagementRate'] * 100)}% engagement, "
                         f"{_int(r['averageSessionDuration'])}s.</p>")
        note = notes.get(cat)
        if note is not None:
            line = (f"{p}Nota: <i>{_esc(note['title'])}</i> "
                    f"(score: {_int(note['editorial_score'])}, "
                    f"{_int(note['activeUsers'])} utenti attivi) → "
                    f"{_int(note['engagementRate'] * 100)}% engagement, "
                    f"{_int(note['averageSessionDuration'])}s.")
            if contesto_note.get(cat):
                line += f" {_esc(contesto_note[cat])}"
            parts.append(line + "</p>")
    parts += [
        f"{p}{_esc(chart_sentence)}</p>",
    ]
    if chart_src:
        parts.append(f'<p style="margin:0 0 12px 0;"><img src="{_esc(chart_src)}" alt="Utenti attivi giornalieri" '
                     'style="max-width:100%;height:auto;"></p>')
    parts += [
        f"{p}Una buona serata,</p>",
        f"{p}Manuel De Luzi</p>",
        f"{p}--</p>",
        f"{p}"
        '<a href="https://www.linkedin.com/in/manuel-de-luzi/" style="color:#0a66c2;">LinkedIn</a> | '
        '<a href="https://linktr.ee/mannyotc" style="color:#0a66c2;">Linktree</a></p>',
    ]
    return "\n".join(parts)


def write_classifica_xlsx(df, path):
    df = _valid(df).sort_values("activeUsers", ascending=False, kind="mergesort")
    wb = Workbook()
    ws = wb.active
    ws.title = "Dati"
    ws.append(_XLSX_COLUMNS)
    for rec in df[_XLSX_COLUMNS].to_dict("records"):
        rec["publication_date"] = pd.Timestamp(rec["publication_date"]).to_pydatetime()
        ws.append([rec[c] for c in _XLSX_COLUMNS])
    ws.add_table(Table(displayName="Tabella2", ref=f"A1:H{len(df) + 1}"))
    ws.freeze_panes = "D1"
    wb.save(path)


_KB_COLUMNS = [
    "title", "editorial_score", "publication_date", "author", "category",
    "activeUsers", "screenPageViews", "engagementRate", "averageSessionDuration",
]


def kb_filename(start, end) -> str:
    return f"top_articles_by_category_{start:%Y%m%d}_{end:%Y%m%d}.xlsx"


def write_kb_xlsx(df, path):
    df = _valid(df).sort_values("activeUsers", ascending=False, kind="mergesort")
    wb = Workbook()
    ws = wb.active
    ws.title = "Dati"
    ws.append(_KB_COLUMNS + ["pagePath"])
    for rec in df[_KB_COLUMNS + ["article_id"]].to_dict("records"):
        rec["publication_date"] = pd.Timestamp(rec["publication_date"]).to_pydatetime()
        ws.append([rec[c] for c in _KB_COLUMNS] + [f"/{rec['article_id']}/"])
    wb.save(path)


def reliability_warning(end):
    if end >= INCIDENT_FROM:
        return ("Attenzione: i dati dal 10 novembre 2026 sono inaffidabili "
                "(incidente sito, traffico sospetto).")
    return None
