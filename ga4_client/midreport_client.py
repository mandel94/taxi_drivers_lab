"""
midreport_client.py

Esporta la top N degli articoli per un intervallo di date nel template del
Midreport (foglio "Dati Top 100", tabella "Tabella2", 9 colonne).

Per l'intervallo:
  1. query GA4 per pagePath (come article_score_job.py);
  2. pagePath -> article_id con la regola di fact_ga4_daily; le pagine non articolo
     vengono scartate;
  3. aggrega per articolo e calcola score ed editorial_rank (article_scoring.py);
  4. legge da articles_dim titolo, autore e data di pubblicazione, scarta gli
     articoli esclusi per scelta editoriale (EXCLUDED_TITLE_PATTERNS) e prende i
     primi N per editorial_rank;
  5. categoria: dal percorso GA4 della pagina piu' vista dell'articolo, come nel
     report settimanale (category_mapping.py).

Scrive un file nuovo copiando il template: il template non viene modificato e il
DB non viene scritto. Il calcolo e' sull'intervallo richiesto, quindi lo score
non e' confrontabile con quello delle settimane complete in fact_article_score_period.

Uso (dalla cartella ga4_client):
    export GA4_PROPERTY_ID=394327334
    export DATABASE_URL=postgresql://user:pass@localhost:5437/taxidrivers
    python midreport_client.py --days 3                       # ultimi 3 giorni, oggi incluso
    python midreport_client.py --start 2026-10-26 --end 2026-10-28 --top 100
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import os
import re
import shutil
import sys
from pathlib import Path

import openpyxl
import pandas as pd
import psycopg2

from article_score_job import PAGE_PATH_COLUMN, attach_article_ids, fetch_week_pages
from article_scoring import combine_pages_by_article, score_articles
from category_mapping import map_category

DEFAULT_TEMPLATE = Path(
    r"C:\Users\manuel.deluzi\OneDrive - Havas\Projects\personali\taxi_drivers\reports\weekly"
    r"\Midreports\Taxi Drivers MidReports 2026\top_100_articles_week 42.xlsx"
)
SHEET_NAME = "Dati Top 100"
TABLE_NAME = "Tabella2"
DATE_COLUMN = 3  # publication_date (colonna C): il formato si prende dal template
HEADERS = [
    "title",
    "editorial_score",
    "publication_date",
    "author",
    "category",
    "activeUsers",
    "screenPageViews",
    "engagementRate",
    "averageSessionDuration",
]


# Articoli mai inclusi nella top: scelta editoriale, applicata dopo lo score
# (il calcolo dei percentili resta sul set completo, come nel report settimanale).
EXCLUDED_TITLE_PATTERNS = [
    r"5 attrici famose che facevano le pornostar",
    r"streaming.*(gratis|gratuit)|(gratis|gratuit).*streaming",
]
_EXCLUDED_TITLE_RE = re.compile("|".join(f"(?:{p})" for p in EXCLUDED_TITLE_PATTERNS), re.IGNORECASE)


def is_excluded_title(title) -> bool:
    return isinstance(title, str) and bool(_EXCLUDED_TITLE_RE.search(html.unescape(title)))


def is_listing_path(path) -> bool:
    """Pagina di elenco (categoria, archivio, home): niente id numerico iniziale e niente .html.
    Gli articoli hanno /<id>/... oppure finiscono in .html; il fallback per slug di ga4_service
    attribuirebbe un elenco come /serie-tv a un articolo con lo stesso slug (D-07 della KB)."""
    clean = str(path).split("?")[0].split("#")[0].strip("/")
    if not clean:
        return True
    segments = clean.split("/")
    return not segments[0].isdigit() and not segments[-1].lower().endswith(".html")


def drop_listing_pages(pages: pd.DataFrame) -> pd.DataFrame:
    return pages[~pages[PAGE_PATH_COLUMN].map(is_listing_path)].reset_index(drop=True)


def dominant_category(pages: pd.DataFrame) -> pd.DataFrame:
    """Per articolo, la categoria del percorso con piu' activeUsers."""
    ranked = pages.assign(activeUsers=pd.to_numeric(pages["activeUsers"], errors="coerce").fillna(0))
    top = ranked.sort_values("activeUsers", ascending=False).drop_duplicates("article_id")
    top = top.assign(category=top[PAGE_PATH_COLUMN].map(map_category))
    return top[["article_id", "category"]]


def article_details(conn, article_ids: list[int]) -> pd.DataFrame:
    """Titolo, autore e data di pubblicazione da articles_dim."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT article_id, title, author_name, published_at FROM articles_dim "
            "WHERE article_id = ANY(%s)",
            (article_ids,),
        )
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["article_id", "title", "author", "published_at"])


def build_top(conn, client, property_id: str, start: dt.date, end: dt.date, top: int,
              with_article_id: bool = False, exclude=()) -> pd.DataFrame:
    if exclude:
        # giorni esclusi (es. blocco del sito): un intervallo GA4 per ogni tratto contiguo.
        # Gli utenti attivi di un articolo presente in piu' tratti si sommano (leggera sovrastima).
        from midreport_report import date_ranges
        parts = [fetch_week_pages(client, property_id, a, b) for a, b in date_ranges(start, end, exclude)]
        pages = pd.concat(parts, ignore_index=True)
    else:
        pages = fetch_week_pages(client, property_id, start, end)
    matched = attach_article_ids(conn, drop_listing_pages(pages))
    if matched.empty:
        return pd.DataFrame(columns=HEADERS + (["article_id"] if with_article_id else []))

    categories = dominant_category(matched)
    scored = score_articles(combine_pages_by_article(matched)).sort_values("editorial_rank")

    details = article_details(conn, scored["article_id"].tolist())
    merged = scored.merge(details, on="article_id", how="left").merge(categories, on="article_id", how="left")
    merged = merged[~merged["title"].map(is_excluded_title)].head(top)

    out = pd.DataFrame(
        {
            "title": merged["title"].map(lambda t: html.unescape(t) if isinstance(t, str) else t),
            "editorial_score": merged["editorial_score"].round(4),
            "publication_date": pd.to_datetime(merged["published_at"]).dt.tz_localize(None),
            "author": merged["author"],
            "category": merged["category"],
            "activeUsers": merged["activeUsers"].astype(int),
            "screenPageViews": merged["screenPageViews"].astype(int),
            "engagementRate": merged["engagementRate"].astype(float),
            "averageSessionDuration": merged["averageSessionDuration"].astype(float),
        }
    )
    if with_article_id:
        out["article_id"] = merged["article_id"].astype(int)
    return out.reset_index(drop=True)


def write_template(rows: pd.DataFrame, template: Path, output: Path) -> None:
    """Copia il template e sostituisce i dati del foglio, aggiornando il range della tabella."""
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, output)

    wb = openpyxl.load_workbook(output)
    ws = wb[SHEET_NAME]
    date_format = ws.cell(row=2, column=DATE_COLUMN).number_format
    if ws.max_row > 1:
        ws.delete_rows(2, ws.max_row - 1)

    for r, record in enumerate(rows.itertuples(index=False), start=2):
        for c, value in enumerate(record, start=1):
            if isinstance(value, pd.Timestamp):
                value = value.to_pydatetime()
            elif not isinstance(value, str) and pd.isna(value):
                value = None
            cell = ws.cell(row=r, column=c, value=value)
            if c == DATE_COLUMN:
                cell.number_format = date_format

    last_row = max(len(rows) + 1, 2)
    ws.tables[TABLE_NAME].ref = f"A1:I{last_row}"
    wb.save(output)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    window = parser.add_mutually_exclusive_group()
    window.add_argument("--days", type=int, default=3, help="ultimi N giorni, oggi incluso (default 3)")
    window.add_argument("--start", type=dt.date.fromisoformat, help="inizio (YYYY-MM-DD), con --end")
    parser.add_argument("--end", type=dt.date.fromisoformat, help="fine (YYYY-MM-DD), con --start")
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--output", type=Path, help="file di output (default: accanto al template)")
    args = parser.parse_args(argv)
    if args.start and not args.end:
        parser.error("--start richiede --end")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    property_id = os.environ.get("GA4_PROPERTY_ID")
    if not database_url or not property_id:
        print("Imposta DATABASE_URL e GA4_PROPERTY_ID", file=sys.stderr)
        return 2

    if args.start:
        start, end = args.start, args.end
    else:
        end = dt.date.today()
        start = end - dt.timedelta(days=args.days - 1)

    output = args.output or args.template.parent / f"top_{args.top}_articles_{start:%Y%m%d}_{end:%Y%m%d}.xlsx"

    from ga4_client import GA4Client  # import tardivo: serve solo alle run reali

    conn = psycopg2.connect(database_url.replace("postgresql+psycopg2://", "postgresql://"))
    try:
        rows = build_top(conn, GA4Client(), property_id, start, end, args.top)
    finally:
        conn.close()

    write_template(rows, args.template, output)
    print(f"[midreport] {start}..{end}: {len(rows)} articoli -> {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
