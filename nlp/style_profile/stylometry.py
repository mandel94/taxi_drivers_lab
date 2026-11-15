"""
stylometry.py

Controllo d'insieme: Cosine Delta (Smith e Aldridge, 2011) sulle parole piu'
frequenti, quasi tutte parole funzionali (articoli, preposizioni, pronomi,
congiunzioni). Riassume in un numero molti tratti che le metriche per
sezione guardano uno alla volta.

Il confronto e' sempre a parita' di unita': se il testo da controllare
contiene intro, "Prima di lasciarci" e sguardo, i tuoi testi di riferimento
sono le stesse sezioni dei tuoi articoli, e gli articoli degli altri autori
vengono tagliati alla stessa lunghezza. Cosi' la distanza non dipende dalla
lunghezza.

Lettura:
- i tuoi testi danno la distanza "normale" (lascia-uno-fuori: ogni tuo
  articolo contro il profilo costruito sugli altri);
- gli altri autori danno la distanza di chi non sei tu;
- un testo generato riuscito cade nel raggio dei tuoi testi.
Su testi di poche centinaia di parole la separazione e' debole: il report
lo dice quando succede.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter

from nlp.style_profile import config

N_MFW = 100
_TOKEN = re.compile(r"[a-zàáèéìíòóùú]+")

# La formula d'apertura dell'intro e' identica in ogni articolo: lasciarla
# nel confronto premierebbe chi la copia, non chi scrive come te.
_FORMULA = re.compile(
    r"(se mai vi foste persi nel rumore|vi siete persi qualcosa questa settimana)[^.]*\.(\s*ecco[^.]*\.)?",
    re.IGNORECASE,
)


def strip_formula(text: str) -> str:
    return _FORMULA.sub(" ", text)


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(strip_formula(text).lower().replace("’", "'"))


def rel_freqs(tokens: list[str], vocab: list[str]) -> list[float]:
    c = Counter(tokens)
    n = len(tokens) or 1
    return [c[w] / n for w in vocab]


def _zscores(rows: list[list[float]]) -> tuple[list[float], list[float]]:
    k = len(rows[0])
    means = [sum(r[j] for r in rows) / len(rows) for j in range(k)]
    sds = []
    for j in range(k):
        var = sum((r[j] - means[j]) ** 2 for r in rows) / max(len(rows) - 1, 1)
        sds.append(math.sqrt(var) or 1e-9)
    return means, sds


def _z(row: list[float], means: list[float], sds: list[float]) -> list[float]:
    return [(x - m) / s for x, m, s in zip(row, means, sds)]


def cosine_delta(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return 1.0 - dot / (na * nb) if na and nb else 1.0


def _centroid(rows: list[list[float]]) -> list[float]:
    return [sum(col) / len(rows) for col in zip(*rows)]


def author_units(section_types: list[str]) -> list[str]:
    """Le stesse sezioni del testo controllato, una unita' per tuo articolo."""
    wanted = set(section_types)
    by_article: dict[int, list[str]] = {}
    for line in open(config.CORPUS_JSONL, encoding="utf-8"):
        r = json.loads(line)
        if r["split"] != "train" or r["section_type"] not in wanted:
            continue
        by_article.setdefault(r["article_id"], []).append(r["text_plain"])
    return ["\n\n".join(v) for v in by_article.values()]


def other_units(n_words: int) -> list[str]:
    out = []
    for line in open(config.OTHERS_JSONL, encoding="utf-8"):
        words = json.loads(line)["text_plain"].split()
        if len(words) >= n_words:
            out.append(" ".join(words[:n_words]))
    return out


def _quantile(v: list[float], q: float) -> float:
    v = sorted(v)
    pos = q * (len(v) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def distance_report(text: str, section_types: list[str]) -> dict | None:
    authors = author_units(section_types)
    if len(authors) < 4:
        return None
    n_words = len(strip_formula(text).split())
    # Gli altri autori tagliati alla lunghezza media delle tue unita', per
    # confrontare testi di dimensione simile.
    ref_len = max(n_words, int(sum(len(strip_formula(a).split()) for a in authors) / len(authors)))
    others = other_units(ref_len)

    a_tok = [tokenize(t) for t in authors]
    o_tok = [tokenize(t) for t in others]
    total = Counter()
    for toks in a_tok + o_tok:
        n = len(toks) or 1
        for w, c in Counter(toks).items():
            total[w] += c / n
    vocab = [w for w, _ in total.most_common(N_MFW)]

    a_rows = [rel_freqs(t, vocab) for t in a_tok]
    o_rows = [rel_freqs(t, vocab) for t in o_tok]
    means, sds = _zscores(a_rows + o_rows)
    a_z = [_z(r, means, sds) for r in a_rows]
    o_z = [_z(r, means, sds) for r in o_rows]
    centroid = _centroid(a_z)

    loo = []
    for i, z in enumerate(a_z):
        rest = a_z[:i] + a_z[i + 1:]
        loo.append(cosine_delta(z, _centroid(rest)))
    other_d = [cosine_delta(z, centroid) for z in o_z]
    d_text = cosine_delta(_z(rel_freqs(tokenize(text), vocab), means, sds), centroid)

    a_max = max(loo)
    separation = sum(d > a_max for d in other_d) / len(other_d) if other_d else 0.0
    if d_text <= a_max:
        verdict = "Il testo cade nel raggio dei tuoi articoli."
    elif other_d and d_text < _quantile(other_d, 0.10):
        verdict = "Il testo è fuori dal raggio dei tuoi articoli, ma più vicino a te che agli altri autori."
    else:
        verdict = "Il testo è più vicino agli altri autori del sito che ai tuoi articoli."
    note = (
        f"Sezioni confrontate: {', '.join(sorted(set(section_types)))}; {n_words} parole; "
        f"{len(authors)} tuoi articoli e {len(others)} di altri autori come riferimento. "
        f"Il {separation:.0%} degli articoli di altri autori cade fuori dal raggio dei tuoi testi"
    )
    note += "." if separation >= 0.7 else ": a questa lunghezza la misura distingue poco, leggila come indizio."
    return {
        "testo": d_text,
        "autore_min": min(loo),
        "autore_max": a_max,
        "altri_p10": _quantile(other_d, 0.10) if other_d else float("nan"),
        "altri_mediana": _quantile(other_d, 0.50) if other_d else float("nan"),
        "separazione": separation,
        "sintesi": verdict,
        "nota": note,
    }
