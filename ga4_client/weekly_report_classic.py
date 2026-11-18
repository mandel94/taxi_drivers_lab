"""
ga4_client/weekly_report_classic.py

Parte meccanica del report settimanale classico di TaxiDrivers (formato WhatsApp,
regole della skill td-weekly-report-builder): top contenuti per categoria,
classifiche, top engagement, top minutaggio, top trailers e note per Manuel.
La sezione "ANALISI DEI TREND" resta il segnaposto {{ANALISI}}: la scrive Claude.

Uso (dalla cartella ga4_client):
    python weekly_report_classic.py --xlsx <top_articles_by_category_AAAAMMGG_AAAAMMGG.xlsx>
        [--prev-xlsx <file settimana precedente>] [--out-dir <cartella>] [--days-note "testo"]
Scrive report_settimanale_DDMMYY_DDMMYY.txt e report_dati.json.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from midreport_client import is_excluded_title

SECTIONS = [
    ("🔎", "Si farà"), ("🎉", "Festival di Cinema"), ("🎬", "Recensioni"), ("📺", "Serie TV"),
    ("📰", "News"), ("📡", "Live Streaming On Demand"), ("📖", "Speciali e Magazine"),
]
EXCLUDED_PATH_RE = re.compile(r"cineblog|altadefinizione|streaming-gratis|pornostar", re.I)
MIN_ER = 0.35
SMALL_SAMPLE = 20


def parse_period(name: str):
    m = re.search(r"(\d{8})_(\d{8})", name)
    if not m:
        raise ValueError(f"Nome file senza periodo AAAAMMGG_AAAAMMGG: {name}")
    return tuple(dt.datetime.strptime(x, "%Y%m%d").date() for x in m.groups())


def ddmmyy(d) -> str:
    return f"{d:%d%m%y}"


def clean_title(t) -> str:
    s = str(t or "").strip()
    for a in "‘’“”«»":
        s = s.replace(a, "'")
    return s


def load(xlsx) -> pd.DataFrame:
    raw = pd.read_excel(xlsx)
    df = pd.DataFrame({
        "title": raw["title"], "author": raw.get("author", ""), "category": raw["category"],
        "pagePath": raw.get("pagePath", ""), "users": pd.to_numeric(raw["activeUsers"], errors="coerce").fillna(0),
        "views": pd.to_numeric(raw.get("screenPageViews", 0), errors="coerce").fillna(0),
        "er": pd.to_numeric(raw["engagementRate"], errors="coerce").fillna(0),
        "dur": pd.to_numeric(raw["averageSessionDuration"], errors="coerce").fillna(0),
        "pub": pd.to_datetime(raw.get("publication_date"), errors="coerce").dt.tz_localize(None),
    })
    df["bounce"] = pd.to_numeric(raw["bounceRate"], errors="coerce") if "bounceRate" in raw else 1 - df["er"]
    df["anomaly"] = raw["anomaly_flag"].astype(str).str.lower().eq("true") if "anomaly_flag" in raw else False
    df["title"] = df["title"].map(lambda t: "" if pd.isna(t) else clean_title(t))
    df["pagePath"] = df["pagePath"].fillna("").astype(str)
    df["author"] = df["author"].fillna("").astype(str)
    return df


def split_exclusions(df):
    mask = df["title"].map(is_excluded_title) | df["pagePath"].map(lambda p: bool(EXCLUDED_PATH_RE.search(p)))
    return df[~mask].copy(), df[mask].copy()


def clean_set(df):
    ok = ((df["title"] != "") & ~((df["er"] == 0) & (df["bounce"] == 1)) & (df["dur"] >= 5)
          & (df["er"] >= MIN_ER) & ~df["anomaly"])
    return df[ok].sort_values(["users", "views"], ascending=False, kind="mergesort")


def pick_cluster(users, lo=3, hi=6):
    """Quante voci tenere: 3-6 seguendo i salti naturali e senza spezzare un pari merito."""
    n = min(len(users), lo)
    while n < min(len(users), hi) and users[n - 1] - users[n] <= max(1, 0.2 * users[n - 1]):
        n += 1
    while 0 < n < len(users) and users[n] == users[n - 1]:
        back = n
        while back > 0 and users[back - 1] == users[n]:
            back -= 1
        if back >= lo:
            n = back
            break
        while n < len(users) and users[n] == users[n - 1]:
            n += 1
    return n


def top_by_category(clean):
    out = {}
    for _, cat in SECTIONS:
        sub = clean[clean["category"] == cat]
        if sub.empty:
            continue
        sub = sub.head(pick_cluster(sub["users"].tolist(), 3, 6) if len(sub) > 3 else len(sub))
        out[cat] = sub
    return out


def category_shares(raw):
    tot = raw["users"].sum()
    return (raw.groupby("category")["users"].sum() / tot * 100).sort_values(ascending=False) if tot else pd.Series(dtype=float)


def category_er(raw, min_articles=3):
    g = raw[raw["category"] != "Altro"].groupby("category")
    res = {}
    for cat, sub in g:
        if len(sub) >= min_articles and sub["users"].sum() > 0:
            res[cat] = float((sub["er"] * sub["users"]).sum() / sub["users"].sum() * 100)
    return pd.Series(res).sort_values(ascending=False)


def arrow(cur, prev, threshold=0.5):
    if prev is None or (isinstance(prev, float) and np.isnan(prev)):
        return "_(—)_"
    d = cur - prev
    return "_(↑)_" if d > threshold else "_(↓)_" if d < -threshold else "_(=)_"


def fmt_item(r, with_cat=False, idx=None):
    base = f"{clean_title(r['title'])} ({r['author']})" if r["author"] else clean_title(r["title"])
    if idx is not None:
        base = f"{idx}. {base}" + (f" [{r['category']}]" if with_cat else "")
    else:
        base = f"• {base}"
    return base


def build(df_raw, start, end, prev=None, days_note=None):
    raw, excluded = split_exclusions(df_raw)
    clean = clean_set(raw)
    cats = top_by_category(clean)
    sh = category_shares(raw)
    er = category_er(raw)
    prev_sh = category_shares(split_exclusions(prev)[0]) if prev is not None else None
    prev_er = category_er(split_exclusions(prev)[0]) if prev is not None else None
    top_er = clean.sort_values(["er", "users"], ascending=False, kind="mergesort").head(10)
    top_dur = clean.sort_values(["dur", "users"], ascending=False, kind="mergesort").head(8)
    tr = clean[(clean["category"] == "Trailers") & (clean["pub"] >= pd.Timestamp(start))
               & (clean["pub"] < pd.Timestamp(end) + pd.Timedelta(days=1))].head(5)

    L = ["*📊 Report Settimanale*", f"*{ddmmyy(start)} – {ddmmyy(end)}*", "",
         "Eccoci col nuovo report settimanale.",
         f"Abbiamo coperto il periodo che va dal {ddmmyy(start)} al {ddmmyy(end)}."]
    if days_note:
        L.append(days_note)
    L += ["Come sempre, la classifica è ordinata per numero di utenti attivi che hanno letto l'articolo.",
          "In fondo troverete lo specchietto che approfondisce il coinvolgimento degli articoli.", "",
          "*TOP CONTENUTI DELLA SETTIMANA*", ""]
    for emoji, cat in SECTIONS:
        if cat in cats:
            L.append(f"*{emoji} {cat}*")
            L += [fmt_item(r) for _, r in cats[cat].iterrows()]
            L.append("")
    L += ["---", "", "*CLASSIFICHE*", "", "*Per utenti attivi*"]
    for cat, v in sh.head(3).items():
        L.append(f"• {cat} ({v:.0f}%) {arrow(v, None if prev_sh is None else prev_sh.get(cat, np.nan))}")
    L += ["", "*Per engagement (% persone che cominciano a leggere l'articolo dopo averlo aperto)*"]
    for cat, v in er.head(3).items():
        L.append(f"• {cat} ({v:.0f}%) {arrow(v, None if prev_er is None else prev_er.get(cat, np.nan))}")
    L += ["", "---", "", "*ANALISI DEI TREND*", "", "{{ANALISI}}", "", "---", "", "*TOP ENGAGEMENT*", ""]
    L += [fmt_item(r, True, i) for i, (_, r) in enumerate(top_er.iterrows(), 1)]
    L += ["", "*TOP MINUTAGGIO*", ""]
    L += [fmt_item(r, True, i) for i, (_, r) in enumerate(top_dur.iterrows(), 1)]
    L += ["", "*TOP TRAILERS*", ""]
    L += [fmt_item(r, False, i) for i, (_, r) in enumerate(tr.iterrows(), 1)] or ["(nessun trailer del periodo sopra i filtri)"]
    L += ["", "---", "", "Come sempre, congratulazioni agli autori entrati in classifica 👏👏👏",
          "Ci vediamo al prossimo report!", ""]

    shown = pd.concat([*cats.values(), top_er, top_dur, tr]).drop_duplicates("pagePath" if raw["pagePath"].any() else "title")
    old = shown[shown["pub"] < pd.Timestamp(start) - pd.DateOffset(months=6)]
    small = lambda d: [f"{clean_title(r['title'])} ({int(r['users'])} utenti attivi)" for _, r in d.iterrows() if r["users"] < SMALL_SAMPLE]
    notes = ["NOTE PER MANUEL (da non pubblicare)", ""]
    notes.append("- Frecce di trend: " + ("calcolate rispetto al file della settimana precedente (soglia 0,5 punti)." if prev is not None
                 else "non calcolabili, manca il dataset precedente (_(—)_)."))
    if days_note:
        notes.append("- Periodo non standard (vedi riga in apertura): i confronti con le settimane intere, frecce comprese, sono indicativi.")
    notes.append("- Esclusioni permanenti applicate: " + (
        "; ".join(f"{clean_title(r['title'])} ({int(r['users'])} utenti attivi)" for _, r in excluded.iterrows()) or "nessun articolo coinvolto") + ".")
    nt = df_raw[df_raw["title"] == ""]
    notes.append("- Righe senza titolo escluse: " + (f"{len(nt)} ({int(nt['users'].sum())} utenti attivi)." if len(nt) else "nessuna."))
    notes.append("- Articoli con data oltre 6 mesi inclusi: " + (
        "; ".join(f"{clean_title(r['title'])} ({r['pub']:%d/%m/%Y})" for _, r in old.iterrows()) if len(old) else "nessuno") + ".")
    notes.append("- Top engagement su campioni piccoli (meno di 20 utenti attivi): " + ("; ".join(small(top_er)) or "nessuno") + ".")
    notes.append("- Top minutaggio su campioni piccoli: " + ("; ".join(small(top_dur)) or "nessuno") + ".")
    altro = raw[raw["category"] == "Altro"]
    notes.append("- Categoria Altro esclusa dalla classifica engagement: " + (
        f"engagement pesato {(altro['er'] * altro['users']).sum() / altro['users'].sum() * 100:.0f}% su {len(altro)} articoli." if altro["users"].sum() > 0 else "assente."))
    late = raw[raw["pub"] >= pd.Timestamp(end) + pd.Timedelta(days=1)]
    notes.append("- Articoli pubblicati dopo l'ultima data: " + (str(len(late)) if len(late) else "nessuno") + ".")
    notes.append("- Le % di categoria sommano utenti attivi per articolo: non sono utenti unici.")

    data = {
        "start": start.isoformat(), "end": end.isoformat(), "n_articles_raw": len(raw),
        "users_sum": int(raw["users"].sum()),
        "category_share": {k: round(float(v), 1) for k, v in sh.items()},
        "category_er": {k: round(float(v), 1) for k, v in er.items()},
        "category_n": raw.groupby("category").size().to_dict(),
        "prev_category_share": None if prev_sh is None else {k: round(float(v), 1) for k, v in prev_sh.items()},
        "prev_category_er": None if prev_er is None else {k: round(float(v), 1) for k, v in prev_er.items()},
    }
    return "\n".join(L + notes) + "\n", data


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--xlsx", type=Path, required=True)
    p.add_argument("--prev-xlsx", type=Path)
    p.add_argument("--out-dir", type=Path)
    p.add_argument("--days-note")
    a = p.parse_args(argv)
    start, end = parse_period(a.xlsx.name)
    prev = load(a.prev_xlsx) if a.prev_xlsx else None
    text, data = build(load(a.xlsx), start, end, prev, a.days_note)
    out = a.out_dir or a.xlsx.parent
    out.mkdir(parents=True, exist_ok=True)
    name = f"report_settimanale_{ddmmyy(start)}_{ddmmyy(end)}.txt"
    (out / name).write_text(text, encoding="utf-8", newline="\n")
    (out / "report_dati.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"[report] {out / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
