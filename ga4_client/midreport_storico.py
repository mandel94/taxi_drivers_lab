"""
ga4_client/midreport_storico.py

Storico dei midreport come consegnati (contratto: nlp/midreport_style/CONTRATTO_STORICO.md, sezione A).
Nessun DB, nessuna rete.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
from pathlib import Path

JSONL_NAME = "midreports.jsonl"
CSV_NAME = "midreport_items.csv"
ITEM_COLUMNS = ["week_id", "category", "kind", "rank", "title",
                "score", "users", "engagement", "duration_s", "metric"]

_MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu",
           "lug", "ago", "set", "ott", "nov", "dic"]


def _py(x):
    return x.item() if hasattr(x, "item") else x


def _reduce(row) -> dict:
    return {
        "title": row["title"],
        "score": _py(row["editorial_score"]),
        "users": _py(row["activeUsers"]),
        "engagement": _py(row["engagementRate"]),
        "duration_s": _py(row["averageSessionDuration"]),
    }


def build_record(start, end, subject, sintesi, sections, notes, insights=None,
                 chart_sentence="", reliability_warning=None, category_stats=None,
                 n_articles=None, metric="utenti", drive_folder_id=None,
                 gmail_draft_id=None, source="workflow") -> dict:
    return {
        "week_id": start.isoformat(),
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "iso_week": start.isocalendar()[1],
        "subject": subject,
        "sintesi": list(sintesi),
        "insights": list(insights) if insights is not None else [],
        "chart_sentence": chart_sentence,
        "reliability_warning": reliability_warning,
        "category_stats": category_stats,
        "n_articles": n_articles,
        "metric": metric,
        "drive_folder_id": drive_folder_id,
        "gmail_draft_id": gmail_draft_id,
        "source": source,
        "sections": {c: [_reduce(r) for r in rows] for c, rows in sections.items()},
        "notes": {c: [_reduce(r)] for c, r in notes.items()},
    }


def items_rows(record) -> list[dict]:
    rows = []

    def add(cat, kind, rank, r):
        rows.append({
            "week_id": record["week_id"], "category": cat, "kind": kind, "rank": rank,
            "title": r["title"], "score": r["score"], "users": r["users"],
            "engagement": r["engagement"], "duration_s": r["duration_s"],
            "metric": record["metric"],
        })

    for cat, items in record["sections"].items():
        for i, r in enumerate(items, 1):
            add(cat, "item", i, r)
    for cat, items in record["notes"].items():
        for r in items:
            add(cat, "nota", 0, r)
    return rows


def load_weeks(folder) -> list[dict]:
    path = Path(folder) / JSONL_NAME
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return sorted((json.loads(line) for line in lines if line.strip()),
                  key=lambda r: r["week_id"])


def upsert_week(folder, record) -> Path:
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    weeks = [w for w in load_weeks(folder) if w["week_id"] != record["week_id"]]
    weeks.append(record)
    weeks.sort(key=lambda r: r["week_id"])
    path = folder / JSONL_NAME
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for w in weeks:
            f.write(json.dumps(w, ensure_ascii=False, default=_py) + "\n")
    with open(folder / CSV_NAME, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=ITEM_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for w in weeks:
            writer.writerows(items_rows(w))
    return path


# --- parser dei report inviati --------------------------------------------

_W = r"([A-Za-zÀ-ù]+)"
_SUBJ_SAME = re.compile(rf"\((\d{{1,2}})\s*[-–—]\s*(\d{{1,2}})\s+{_W}\s+(\d{{4}})\)")
_SUBJ_CROSS = re.compile(rf"\((\d{{1,2}})\s+{_W}\s*[-–—]\s*(\d{{1,2}})\s+{_W}\s+(\d{{4}})\)")
_DAL_SAME = re.compile(rf"dal\s+(\d{{1,2}})\s+al\s+(\d{{1,2}})\s+{_W}(?:\s+(\d{{4}}))?")
_DAL_CROSS = re.compile(rf"dal\s+(\d{{1,2}})\s+{_W}\s+al\s+(\d{{1,2}})\s+{_W}(?:\s+(\d{{4}}))?")

_NUM = r"(\d+(?:[.,]\d+)?)"
_ITEM = re.compile(
    rf"^[•\-]\s*(.+?)\s*\(score:\s*{_NUM}\)\s*(?:→|->)\s*{_NUM}\s+(?:utenti attivi|views),"
    rf"\s*{_NUM}%\s*engagement(?:,\s*{_NUM}\s*s)?")
_NOTA = re.compile(
    rf"^Nota:\s*(.+?)\s*\(score:\s*{_NUM},\s*{_NUM}\s+(?:utenti attivi|views)\)\s*(?:→|->)\s*"
    rf"{_NUM}%\s*engagement(?:,\s*{_NUM}\s*s)?")
_HEADER = re.compile(r"^([^•'()→:]{1,60}):$")
_GLUED = re.compile(r"^([^•'()→:]{1,60}:)\s*(•.*)$")


def _is_item_par(cur):
    return cur[0][0] == "•" or cur[0].startswith(("- ", "Nota:"))


def _month(word):
    return _MONTHS.index(word.lower()[:3]) + 1


def _num(s):
    v = float(s.replace(",", "."))
    return int(v) if v == int(v) else v


def _period(text, email_date):
    try:
        m = _SUBJ_SAME.search(text)
        if m:
            d1, d2, mon, y = int(m[1]), int(m[2]), _month(m[3]), int(m[4])
            return dt.date(y, mon, d1), dt.date(y, mon, d2)
        m = _SUBJ_CROSS.search(text)
        if m:
            y, m2 = int(m[5]), _month(m[4])
            m1 = _month(m[2])
            return dt.date(y - (m1 > m2), m1, int(m[1])), dt.date(y, m2, int(m[3]))
        m = _DAL_SAME.search(text)
        if m:
            mon = _month(m[3])
            y = int(m[4]) if m[4] else email_date.year - (mon > email_date.month)
            return dt.date(y, mon, int(m[1])), dt.date(y, mon, int(m[2]))
        m = _DAL_CROSS.search(text)
        if m:
            m1, m2 = _month(m[2]), _month(m[4])
            y = int(m[5]) if m[5] else email_date.year - (m2 > email_date.month)
            return dt.date(y - (m1 > m2), m1, int(m[1])), dt.date(y, m2, int(m[3]))
    except ValueError:
        pass
    start = email_date - dt.timedelta(days=email_date.weekday() + 7)
    return start, start + dt.timedelta(days=4)


def _logical_lines(text):
    """Unisce le righe a capo: ogni voce (elenco, Nota, paragrafo) diventa una riga."""
    out, cur = [], None
    raws = []
    for raw in text.replace("*", "").splitlines():
        g = _GLUED.match(raw.strip())
        raws.extend(g.groups() if g else [raw])
    for raw in raws:
        line = raw.strip()
        if not line:
            cur = None
            continue
        if line[0] == "•" or line.startswith("- ") or line.startswith("Nota:") \
                or cur is None or (_HEADER.match(line) and not _is_item_par(cur)):
            cur = [line]
            out.append(cur)
        else:
            cur.append(line)
    return [" ".join(parts) for parts in out]


def parse_sent_report(text, email_date) -> dict:
    start, end = _period(text, email_date)
    sintesi, sections, notes = [], {}, {}
    subject_line, chart, cat = "", "", None
    lines = _logical_lines(text)
    for line in lines:
        header = _HEADER.match(line)
        if header:
            cat = header[1].strip()
            continue
        if line[0] in "•-" and cat is not None and cat.lower() in ("in sintesi", "in breve"):
            sintesi.append(line.lstrip("•- ").strip())
            continue
        if cat is None and line.startswith("- ") and not _ITEM.match(line):
            sintesi.append(line.lstrip("•- ").strip())
            continue
        m = _ITEM.match(line)
        if m and cat is not None:
            sections.setdefault(cat, []).append(_raw(m))
            continue
        m = _NOTA.match(line)
        if m and cat is not None:
            notes[cat] = _raw(m)
            continue
        if not subject_line and "Midreport Settimana" in line:
            subject_line = line
        if not chart and "trend" in line.lower() and line[0] not in "•-":
            chart = re.split(r"\[image|Una buona", line)[0].strip()
    if not sintesi and not sections and not notes:
        for line in lines[1:]:
            if line.startswith(("Una buona", "A presto", "Buon", "--")):
                break
            sintesi.append(line)
    metric = "utenti" if "utenti attivi" in text else "views"
    return build_record(start, end, subject_line, sintesi, sections, notes,
                        chart_sentence=chart, metric=metric, source="gmail")


def _raw(m):
    return {
        "title": m[1][1:-1] if len(m[1]) > 1 and m[1][0] == m[1][-1] == "'" else m[1],
        "editorial_score": _num(m[2]),
        "activeUsers": int(_num(m[3])),
        "engagementRate": float(m[4].replace(",", ".")) / 100,
        "averageSessionDuration": _num(m[5]) if m[5] is not None else None,
    }
