"""
db_explore.py

Client CLI per l'interrogazione esplorativa del warehouse (sola lettura).
Riusa la connessione di data_access/db.py: le stesse credenziali del .env.

Comandi:

  articles   Visualizzazioni e sessioni per articolo e giorno, con sezione,
             categorie WordPress, eta' e lunghezza. Un CSV "giorno" (una riga
             per articolo e giorno) e, con --summary, un CSV "riepilogo" (una
             riga per articolo sull'intero intervallo).

  query      Esegue un file SQL di sola lettura e salva il risultato in CSV.

Esempi (dalla root del progetto):

  python scripts/db_explore.py articles --days 7
  python scripts/db_explore.py articles --start 2026-10-10 --end 2026-10-16 --summary
  python scripts/db_explore.py query --file scripts/sql/mio_check.sql --out exports/check.csv

Di default l'intervallo termina ieri (il giorno corrente e' incompleto) e i CSV
finiscono in exports/, che non va in git (vedi .gitignore).
"""

from __future__ import annotations

import argparse
import html
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_access.db import query_df  # noqa: E402

EXPORT_DIR = ROOT / "exports"

# Una riga per articolo e giorno, con le dimensioni che servono a capire la
# composizione editoriale. Le sessioni attribuite sono per articolo: sommarle
# tra articoli non ha senso, sommarle tra giorni dello stesso articolo si'.
DAILY_SQL = """
select
    m.date_day,
    m.article_id,
    m.title,
    m.link,
    a.published_date,
    a.word_count,
    m.section_key       as day_section_key,
    m.section_name      as day_section_name,
    a.primary_section_key,
    m.age_days,
    m.age_bucket,
    m.is_new_30d,
    m.views,
    m.sessions_attributed,
    m.engaged_sessions_attributed,
    m.engagement_seconds,
    m.is_provisional
from marts.mart_article_daily m
join marts.dim_article a using (article_id)
where m.date_day between %(start)s and %(end)s
order by m.date_day, m.views desc
"""

# Tutte le sezioni e tutte le categorie WordPress assegnate a ciascun articolo.
# Una riga per articolo, con liste separate da ' | '.
ARTICLE_TAXONOMY_SQL = """
select
    a.article_id,
    coalesce(s.sections, '')   as sections,
    coalesce(c.categories, '') as categories
from marts.dim_article a
left join (
    select article_id, string_agg(section_key, ' | ' order by section_key) as sections
    from intermediate.int_article_section
    group by article_id
) s using (article_id)
left join (
    select sac.article_id, string_agg(distinct cat.name, ' | ' order by cat.name) as categories
    from staging.stg_article_categories sac
    join staging.stg_categories cat using (category_id)
    group by sac.article_id
) c using (article_id)
where a.article_id = any(%(ids)s)
"""


def default_window(days: int) -> tuple[date, date]:
    """Ultimi `days` giorni chiusi, terminando ieri."""
    end = date.today() - timedelta(days=1)
    return end - timedelta(days=days - 1), end


def _unescape(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """I titoli e le categorie arrivano da WordPress con entita' HTML (&#8216;, &amp;)."""
    for col in columns:
        df[col] = df[col].map(lambda v: html.unescape(v) if isinstance(v, str) else v)
    return df


def load_daily(start: date, end: date) -> pd.DataFrame:
    daily = query_df(DAILY_SQL, {"start": start, "end": end})
    if daily.empty:
        return daily
    tax = query_df(ARTICLE_TAXONOMY_SQL, {"ids": daily["article_id"].unique().tolist()})
    daily = daily.merge(tax, on="article_id", how="left")
    return _unescape(daily, ["title", "categories", "sections"])


def build_summary(daily: pd.DataFrame) -> pd.DataFrame:
    """Una riga per articolo sull'intero intervallo, con le dimensioni 'fisse'."""
    sums = (
        daily.groupby("article_id")
        .agg(
            title=("title", "first"),
            link=("link", "first"),
            published_date=("published_date", "first"),
            word_count=("word_count", "first"),
            primary_section_key=("primary_section_key", "first"),
            sections=("sections", "first"),
            categories=("categories", "first"),
            age_days_last=("age_days", "last"),
            is_new_30d_last=("is_new_30d", "last"),
            first_day_with_views=("date_day", "min"),
            last_day_with_views=("date_day", "max"),
            days_with_views=("date_day", "nunique"),
            views=("views", "sum"),
            sessions_attributed=("sessions_attributed", "sum"),
            engaged_sessions_attributed=("engaged_sessions_attributed", "sum"),
            engagement_seconds=("engagement_seconds", "sum"),
        )
        .reset_index()
    )
    sums["engagement_rate"] = (
        sums["engaged_sessions_attributed"] / sums["sessions_attributed"]
    ).round(4)
    return sums.sort_values("views", ascending=False)


def cmd_articles(args: argparse.Namespace) -> int:
    if args.start or args.end:
        start = date.fromisoformat(args.start) if args.start else None
        end = date.fromisoformat(args.end) if args.end else date.today() - timedelta(days=1)
        if start is None:
            start = end - timedelta(days=args.days - 1)
    else:
        start, end = default_window(args.days)

    daily = load_daily(start, end)
    if daily.empty:
        print(f"Nessun dato per articolo tra {start} e {end}.")
        return 1

    EXPORT_DIR.mkdir(exist_ok=True)
    tag = f"{start:%Y%m%d}_{end:%Y%m%d}"
    day_path = EXPORT_DIR / f"articoli_giorno_{tag}.csv"
    daily.to_csv(day_path, index=False, encoding="utf-8-sig", float_format="%.4f")
    print(f"Giorno:    {day_path}  ({len(daily)} righe, {daily['article_id'].nunique()} articoli)")

    if args.summary:
        summary = build_summary(daily)
        sum_path = EXPORT_DIR / f"articoli_riepilogo_{tag}.csv"
        summary.to_csv(sum_path, index=False, encoding="utf-8-sig", float_format="%.4f")
        print(f"Riepilogo: {sum_path}  ({len(summary)} articoli)")

    print(f"Intervallo: {start} -> {end}. Ultimi giorni possono essere provvisori (colonna is_provisional).")
    return 0


COMPOSITION_SQL = """
select
    week_start_date,
    section_key,
    section_name,
    is_complete_week,
    articles_published,
    articles_active,
    articles_active_prev,
    views,
    views_prev,
    views_share,
    views_per_active_article,
    engagement_seconds
from marts.mart_section_weekly
where week_start_date >= current_date - (%(weeks)s * 7)
order by week_start_date, views desc
"""


def build_composition(weeks: int) -> pd.DataFrame:
    """Sezioni per settimana con variazione sulla settimana precedente.

    Le settimane sono quelle del mart (lunedi), quindi l'ultima puo' essere parziale:
    is_complete_week la segnala.
    """
    df = query_df(COMPOSITION_SQL, {"weeks": weeks})
    df["views_pct_vs_prev"] = (df["views"] / df["views_prev"] - 1).round(4)
    df["articles_active_pct_vs_prev"] = (
        df["articles_active"] / df["articles_active_prev"] - 1
    ).round(4)
    return df


def composition_totals(comp: pd.DataFrame) -> pd.DataFrame:
    """Totale di sito per settimana: quota di ogni sezione sul totale della settimana."""
    totals = (
        comp.groupby("week_start_date")
        .agg(
            views=("views", "sum"),
            articles_published=("articles_published", "sum"),
            articles_active=("articles_active", "sum"),
            is_complete_week=("is_complete_week", "first"),
        )
        .reset_index()
    )
    totals["views_pct_vs_prev"] = totals["views"].pct_change().round(4)
    return totals


def cmd_composition(args: argparse.Namespace) -> int:
    comp = build_composition(args.weeks)
    if comp.empty:
        print("Nessuna settimana nel periodo richiesto.")
        return 1

    EXPORT_DIR.mkdir(exist_ok=True)
    out = EXPORT_DIR / f"composizione_settimanale_ultime{args.weeks}.csv"
    comp.to_csv(out, index=False, encoding="utf-8-sig", float_format="%.4f")
    print(f"{out}  ({len(comp)} righe)")

    # Vista sintetica nel terminale: quota di visualizzazioni per sezione, settimana per colonna.
    share = comp.pivot_table(index="section_name", columns="week_start_date", values="views_share", aggfunc="sum")
    print("\nQuota di visualizzazioni per sezione (0-1):")
    print(share.round(3).to_string())

    totals = composition_totals(comp)
    print("\nTotale di sito (somma delle sezioni):")
    print(totals.to_string(index=False))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    sql = Path(args.file).read_text(encoding="utf-8")
    df = query_df(sql)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig", float_format="%.4f")
    print(f"{out}  ({len(df)} righe)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_art = sub.add_parser("articles", help="Export visualizzazioni e sessioni per articolo")
    p_art.add_argument("--days", type=int, default=7, help="Giorni chiusi da esportare (default 7)")
    p_art.add_argument("--start", help="Data iniziale AAAA-MM-GG (sovrascrive --days)")
    p_art.add_argument("--end", help="Data finale AAAA-MM-GG (default ieri)")
    p_art.add_argument("--summary", action="store_true", help="Produce anche il riepilogo per articolo")
    p_art.set_defaults(func=cmd_articles)

    p_comp = sub.add_parser("composition", help="Composizione per sezione e settimana, con CSV")
    p_comp.add_argument("--weeks", type=int, default=8, help="Settimane da includere (default 8)")
    p_comp.set_defaults(func=cmd_composition)

    p_q = sub.add_parser("query", help="Esegue un file SQL di sola lettura e salva in CSV")
    p_q.add_argument("--file", required=True, help="File .sql con la query")
    p_q.add_argument("--out", required=True, help="CSV di output")
    p_q.set_defaults(func=cmd_query)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
