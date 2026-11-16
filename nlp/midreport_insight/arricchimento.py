"""
arricchimento.py (fase 2)

Dai top e worst di osservazioni.json agli argomenti da misurare fuori dal sito:
  - segnali Wikipedia (visite) e TMDB (popolarita') tramite scripts/external_trend.py;
  - query per le notizie web (le ricerche le lancia l'orchestratore con WebSearch e scrive
    notizie.json; qui nessuna rete per le notizie).

Uso (dalla radice del repo):
    python -m nlp.midreport_insight.arricchimento prepara --dir <cartella settimana> [--no-network]
    python -m nlp.midreport_insight.arricchimento unisci  --dir <cartella settimana>
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
MAX_TOPIC_WORDS = 6
_MONTHS = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
           "settembre", "ottobre", "novembre", "dicembre"]


def _valid_topic(topic) -> bool:
    return isinstance(topic, str) and bool(topic.strip()) and len(topic.split()) <= MAX_TOPIC_WORDS


def select_topics(top_worst: list[dict], max_topics: int = 12) -> list[dict]:
    """Argomenti unici dei top e worst, alternati (top per utenti, worst per rapporto crescente)."""
    def keep(role):
        rows = [r for r in top_worst if r.get("role") == role and _valid_topic(r.get("topic"))]
        key = (lambda r: -r["users"]) if role == "top" else (lambda r: r["ratio_vs_baseline"]
                                                              if r.get("ratio_vs_baseline") is not None else math.inf)
        return sorted(rows, key=key)

    queues = [keep("top"), keep("worst")]
    seen, out, i = set(), [], 0
    while len(out) < max_topics and any(queues):
        q = queues[i % 2]
        i += 1
        while q:
            r = q.pop(0)
            if r["topic"] in seen:
                continue
            seen.add(r["topic"])
            out.append({"topic": r["topic"], "role": r["role"], "category": r.get("category"),
                        "article_id": r.get("article_id"), "title": r.get("title"),
                        "users": r.get("users"), "ratio": r.get("ratio_vs_baseline")})
            break
    return out


def news_queries(topics: list[dict], max_queries: int = 10, today: dt.date | None = None) -> list[dict]:
    today = today or dt.date.today()
    when = f"{_MONTHS[today.month - 1]} {today.year}"
    return [{"topic": t["topic"], "query": f"{t['topic']} novità notizie {when}"} for t in topics[:max_queries]]


def _phase(momentum):
    if momentum is None:
        return None
    return "in crescita" if momentum >= 0.5 else "in calo" if momentum <= -0.5 else "stabile"


def wiki_tmdb_signals(topics: list[dict], end: dt.date, r: int = 7, module=None) -> dict:
    """{topic: {wiki_page, wiki_recent, wiki_prior, momentum, fase, tmdb, tmdb_pop}}; None dove manca il segnale."""
    if module is None:
        sys.path.insert(0, str(ROOT / "scripts"))
        import external_trend as module  # noqa: PLC0415
    key = module.tmdb_key()
    start = end - dt.timedelta(days=2 * r - 1)
    out = {}
    for t in topics:
        label = t["topic"]
        sig = {"wiki_page": None, "wiki_recent": None, "wiki_prior": None, "momentum": None, "fase": None,
               "tmdb": None, "tmdb_pop": None}
        page = module.find_page(label, end.year - 1)
        if page:
            s = module.pageviews(page, start, end)
            recent = float(s[s.index > pd.Timestamp(end) - pd.Timedelta(days=r)].sum())
            prior = float(s.sum()) - recent
            sig.update(wiki_page=f"{page['lang']}: {page['title']}", wiki_recent=recent, wiki_prior=prior,
                       momentum=math.log2((recent / r + 1) / (prior / r + 1)))
            sig["fase"] = _phase(sig["momentum"])
        if key:
            item = module.find_tmdb(label, end.year - 1, key)
            if item:
                sig.update(tmdb=f"{item['media_type']}: {item['title']} ({item['year']})", tmdb_pop=item["popularity"])
        out[label] = sig
    if hasattr(module, "save_cache"):
        module.save_cache()
    return out


def merge_enrichment(top_worst: list[dict], signals: dict, news: dict) -> list[dict]:
    merged = []
    for r in top_worst:
        t = r.get("topic")
        merged.append({**r, "segnali": signals.get(t) if t else None, "notizie": list(news.get(t, [])) if t else []})
    return merged


def _write(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cmd", choices=["prepara", "unisci"])
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--no-network", action="store_true", help="salta Wikipedia e TMDB")
    parser.add_argument("--max-topics", type=int, default=12)
    parser.add_argument("--max-queries", type=int, default=10)
    args = parser.parse_args(argv)

    obs = json.loads((args.dir / "osservazioni.json").read_text(encoding="utf-8"))
    end = dt.date.fromisoformat(obs["week_id"]) + dt.timedelta(days=4)
    if args.cmd == "prepara":
        topics = select_topics(obs["top_worst"], args.max_topics)
        signals = {} if args.no_network else wiki_tmdb_signals(topics, end)
        _write(args.dir / "argomenti.json", {"topics": topics, "queries": news_queries(topics, args.max_queries),
                                              "segnali": signals})
        print(f"[insight] argomenti: {len(topics)}, query notizie: {min(len(topics), args.max_queries)}")
    else:
        arg = json.loads((args.dir / "argomenti.json").read_text(encoding="utf-8"))
        news_path = args.dir / "notizie.json"
        news = json.loads(news_path.read_text(encoding="utf-8")) if news_path.exists() else {}
        _write(args.dir / "arricchimento.json", merge_enrichment(obs["top_worst"], arg["segnali"], news))
        print("[insight] arricchimento.json scritto")
    return 0


if __name__ == "__main__":
    sys.exit(main())
