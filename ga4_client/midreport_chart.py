"""
midreport_chart.py

Grafico degli utenti attivi giornalieri del sito (GA4, dimensione `date`, metrica
`activeUsers`: tutto il sito, non la somma per articolo) per le ultime settimane.
Salva `newplot.png` nella cartella della settimana, da allegare in linea all'email.

Uso (dalla cartella ga4_client):
    python midreport_chart.py --end 2026-11-06 --out ..\\output\\midreport_workflow\\20261102_20261106
    python midreport_chart.py --end 2026-11-15 --mark 2026-11-10,2026-11-11 --out <cartella>
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
_MONTHS = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]


def window(end: dt.date, weeks: int = 7) -> tuple[dt.date, dt.date]:
    """Dal lunedi' di `weeks - 1` settimane prima della settimana di `end`, fino a `end`."""
    monday = end - dt.timedelta(days=end.weekday())
    return monday - dt.timedelta(weeks=weeks - 1), end


def parse_daily(raw: pd.DataFrame) -> pd.DataFrame:
    """Colonne `date` (Timestamp) e `users` (int, NaN nei giorni mancanti), un giorno per riga."""
    df = pd.DataFrame({"date": pd.to_datetime(raw["date"].astype(str), format="%Y%m%d"),
                       "users": pd.to_numeric(raw["activeUsers"])}).sort_values("date")
    full = pd.date_range(df["date"].min(), df["date"].max())
    return df.set_index("date").reindex(full).rename_axis("date").reset_index()


def fetch_daily(client, property_id: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    raw = client.run_query(property_id, metrics=["activeUsers"], dimensions=["date"],
                           start_date=start.isoformat(), end_date=end.isoformat())
    return parse_daily(raw)


def plot_daily_users(df: pd.DataFrame, path, marked_days=(), title: str | None = None) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    fig, ax = plt.subplots(figsize=(9, 3.6), dpi=110)
    ax.plot(df["date"], df["users"], color="#1f4e79", linewidth=1.8, marker="o", markersize=3)
    weekends = df[df["date"].dt.weekday >= 5]
    ax.scatter(weekends["date"], weekends["users"], color="#9aa5b1", s=14, zorder=3, label="sabato e domenica")
    marked = {pd.Timestamp(d) for d in marked_days}
    pts = df[df["date"].isin(marked)]
    if not pts.empty:
        ax.scatter(pts["date"], pts["users"], color="#c0392b", s=34, zorder=4, label="giorni anomali (traffico automatico o blocco)")
    ax.set_ylim(bottom=0)
    ax.set_title(title or "Utenti attivi giornalieri del sito (GA4)", fontsize=11, loc="left")
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=mdates.MO))
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: (lambda d: f"{d.day} {_MONTHS[d.month - 1]}")(mdates.num2date(x))))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}".replace(",", ".")))
    ax.grid(axis="y", color="#e5e7eb")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="lower left")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--end", type=dt.date.fromisoformat, required=True, help="ultimo giorno (YYYY-MM-DD)")
    parser.add_argument("--weeks", type=int, default=7, help="settimane da mostrare (default 7)")
    parser.add_argument("--mark", default="", help="giorni da evidenziare, separati da virgola")
    parser.add_argument("--out", type=Path, required=True, help="cartella della settimana")
    args = parser.parse_args(argv)

    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    property_id = os.environ.get("GA4_PROPERTY_ID")
    if not property_id:
        print("Manca GA4_PROPERTY_ID nel .env", file=sys.stderr)
        return 2
    from ga4_client import GA4Client  # import tardivo

    start, end = window(args.end, args.weeks)
    df = fetch_daily(GA4Client(), property_id, start, end)
    marked = [dt.date.fromisoformat(x) for x in args.mark.split(",") if x.strip()]
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "newplot.png"
    plot_daily_users(df, path, marked)
    df.to_csv(args.out / "utenti_giornalieri.csv", index=False, lineterminator="\n")
    print(f"[midreport] grafico: {path} ({len(df)} giorni, {start}..{end})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
