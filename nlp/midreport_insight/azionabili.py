"""
azionabili.py (fase 2)

Osservazioni da cui nascono le AZIONI per la redazione (pura, nessuna rete):
  - lifecycle: quanti pezzi nuovi con lettori nella settimana d'uscita ci sono ancora la settimana dopo;
  - new_tail: quanti pezzi nuovi restano sotto una soglia di utenti, per categoria;
  - monthly_guides: utenti delle guide mensili delle piattaforme ("<piattaforma> <mese> 2026") per settimana.
Sorgente: stessa history di observe.py (articles_history.csv della KB, traffico sospetto tolto).
"""

from __future__ import annotations

import re

import pandas as pd

from nlp.midreport_insight import observe as ob

_MONTH_YEAR = re.compile(r"\b(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|"
                         r"novembre|dicembre)\s+20\d\d\b", re.IGNORECASE)


def lifecycle(history, min_users: int = 15, max_pub_offset_days: int = 2, min_cat: int = 8) -> dict:
    """Coorte: pezzi usciti nei primi giorni della settimana comparabile W con almeno `min_users` utenti.
    `survival_pct`: quota ancora presente nella lista della settimana W+7 (la lista ha una soglia di
    pochi utenti, quindi gli assenti hanno meno di quella soglia); `retained_pct`: utenti della settimana
    dopo sui soli presenti, in percentuale di quelli della settimana d'uscita (minimo: gli assenti contano 0);
    `median_ratio_survivors`: rapporto mediano tra i presenti."""
    h = ob._prep(history)
    h = h[h["comparable"]].copy()
    h["pub_date"] = pd.to_datetime(h["pub_date"])
    weeks = sorted(h["week_id"].unique())
    rows, per_pair = [], []
    for wk in weeks:
        ws = pd.Timestamp(wk)
        nxt = (ws + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        if nxt not in weeks:
            continue
        a = h[(h["week_id"] == wk) & (h["pub_date"] >= ws)
              & (h["pub_date"] <= ws + pd.Timedelta(days=max_pub_offset_days)) & (h["users"] >= min_users)]
        a = a.sort_values("users", ascending=False).drop_duplicates("article_id")
        if a.empty:
            continue
        b = h[h["week_id"] == nxt].groupby("article_id")["users"].max()
        pair = [(r.category, r.users, b.get(r.article_id)) for r in a.itertuples()]
        rows += pair
        per_pair.append(round(100 * sum(p[2] is not None for p in pair) / len(pair), 1))
    d = pd.DataFrame(rows, columns=["category", "u1", "u2"])
    if d.empty:
        return {"n": 0, "pairs": 0, "survival_pct": None, "retained_pct": None, "median_ratio_survivors": None,
                "by_category": {}, "survival_by_pair": []}
    d["alive"] = d["u2"].notna()
    d["ratio"] = d["u2"] / d["u1"]

    def stats(g):
        return {"n": int(len(g)), "survival_pct": round(100 * g["alive"].mean(), 1),
                "retained_pct": round(100 * g["u2"].fillna(0).sum() / g["u1"].sum(), 1),
                "median_ratio_survivors": None if not g["alive"].any() else round(float(g["ratio"].median()), 2)}

    out = stats(d)
    out.update(pairs=len(per_pair), survival_by_pair=per_pair,
               by_category={c: stats(g) for c, g in d.groupby("category") if len(g) >= min_cat})
    return out


def new_tail(table, max_age_days: int = 14, low: int = 10, min_n: int = 5) -> dict:
    """Pezzi usciti da non piu' di `max_age_days` giorni (tabella di observe.build_table) con meno di
    `low` utenti, per categoria (almeno `min_n` pezzi) e in totale. Restano fuori i pezzi con meno di
    MIN_EXPOSURE_DAYS giorni di vita nella finestra (usciti giovedi' o venerdi')."""
    t = table[(table["age_days"] <= max_age_days) & (table["exposure_days"] >= ob.MIN_EXPOSURE_DAYS)]

    def stats(g):
        n_low = int((g["users"] < low).sum())
        return {"n": int(len(g)), "n_low": n_low, "low_pct": round(100 * n_low / len(g), 1),
                "low_users_pct": round(100 * g.loc[g["users"] < low, "users"].sum() / g["users"].sum(), 1)}

    return {"total": stats(t) if len(t) else {"n": 0, "n_low": 0, "low_pct": None, "low_users_pct": None},
            "by_category": {c: stats(g) for c, g in t.groupby("category") if len(g) >= min_n}}


def monthly_guides(history) -> dict:
    """Guide mensili delle piattaforme (titolo con mese e anno), per settimana comparabile."""
    h = ob._prep(history)
    h = h[h["comparable"]]
    g = h[[isinstance(t, str) and bool(_MONTH_YEAR.search(t)) and ob.classify_format(t, c) == "guida_lista"
           for t, c in zip(h["title"], h["category"])]]
    g = g.sort_values("users", ascending=False).drop_duplicates(["week_id", "article_id"])
    by_week = [{"week_id": wk, "n": int(len(x)), "users": int(x["users"].sum()),
                "median_users": float(x["users"].median())} for wk, x in sorted(g.groupby("week_id"))]
    return {"by_week": by_week}


def main(argv=None):
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Vita degli articoli, coda lunga e guide mensili per una settimana")
    parser.add_argument("--week", required=True, help="lunedi' AAAA-MM-GG")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--kb", type=Path, default=Path(ob.DEFAULT_KB))
    args = parser.parse_args(argv)
    history = pd.read_csv(args.kb / "articles_history.csv")
    data = {"week_id": args.week, "lifecycle": lifecycle(history),
            "new_tail": new_tail(ob.build_table(history, args.week)), "monthly_guides": monthly_guides(history)}
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Scritto {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
