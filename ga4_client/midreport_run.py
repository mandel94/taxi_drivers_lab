"""
midreport_run.py

Esegue il flusso del Midreport per un intervallo: classifica degli articoli da GA4 e DB,
poi scrive "classifica_articoli_week NN.xlsx" e dati.json nella cartella di output.

Uso (dalla cartella ga4_client):
    python midreport_run.py --start 2026-11-02 --end 2026-11-06
    python midreport_run.py --start 2026-11-02 --end 2026-11-06 --out C:\\percorso\\cartella
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import psycopg2
from dotenv import load_dotenv

import midreport_report as rep
from midreport_client import build_top

ROOT = Path(__file__).resolve().parents[1]


def clean(value):
    """Rende serializzabile in JSON: date in ISO, numpy in tipi nativi, NaN in null."""
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url.replace("postgresql+psycopg2://", "postgresql://")
    user = quote_plus(os.environ["POSTGRES_USER"])
    password = quote_plus(os.environ["POSTGRES_PASSWORD"])
    db = os.environ["POSTGRES_DB"]
    port = os.environ["POSTGRES_PORT"]
    return f"postgresql://{user}:{password}@localhost:{port}/{db}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", type=dt.date.fromisoformat, required=True, help="inizio (YYYY-MM-DD)")
    parser.add_argument("--end", type=dt.date.fromisoformat, required=True, help="fine (YYYY-MM-DD)")
    parser.add_argument("--out", type=Path, help="cartella di output (default output/midreport_workflow/<start>_<end>)")
    args = parser.parse_args(argv)
    start, end = args.start, args.end
    out = args.out or ROOT / "output" / "midreport_workflow" / f"{start:%Y%m%d}_{end:%Y%m%d}"

    load_dotenv(ROOT / ".env")
    property_id = os.environ.get("GA4_PROPERTY_ID")
    if not property_id:
        print("Manca GA4_PROPERTY_ID nel .env", file=sys.stderr)
        return 2

    from ga4_client import GA4Client  # import tardivo: serve solo alle run reali

    conn = psycopg2.connect(database_url())
    try:
        df = build_top(conn, GA4Client(), property_id, start, end, top=100000, with_article_id=True)
    finally:
        conn.close()

    out.mkdir(parents=True, exist_ok=True)
    week = start.isocalendar()[1]
    xlsx = out / f"classifica_articoli_week {week:02d}.xlsx"
    rep.write_classifica_xlsx(df, xlsx)
    rep.write_kb_xlsx(df, out / rep.kb_filename(start, end))

    sections = rep.build_sections(df)
    data = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "subject": rep.subject(start, end),
        "week_label": rep.week_label(start, end),
        "reliability_warning": rep.reliability_warning(end),
        "category_stats": rep.category_stats(df),
        "sections": sections,
        "notes": rep.build_notes(df, sections),
        "top5_active_users": df.nlargest(5, "activeUsers").to_dict("records"),
        "n_articles": len(df),
    }
    with open(out / "dati.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(clean(data), f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"[midreport] {data['subject']}")
    print(f"[midreport] articoli: {len(df)}")
    print(f"[midreport] categorie con sezione: {len(sections)}, note: {len(data['notes'])}")
    print(f"[midreport] avviso: {data['reliability_warning'] or 'nessuno'}")
    print(f"[midreport] output: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
