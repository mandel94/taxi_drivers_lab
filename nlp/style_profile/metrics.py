"""
metrics.py

Livello 2 del profilo di stile: metriche quantitative per sezione, calcolate
con spaCy sul corpus di addestramento e usate come intervalli di controllo
sul testo generato (non come obiettivi da centrare).

Comandi (dalla root del progetto):
    .venv\\Scripts\\python.exe -m nlp.style_profile.metrics build
    .venv\\Scripts\\python.exe -m nlp.style_profile.metrics check <file.md> [--out report.md]

`build` legge data/corpus.jsonl (solo split "train") e scrive
metriche_target.yaml. `check` legge un testo in Markdown (convenzioni in
parsing.sections_from_markdown), lo divide in sezioni e confronta ogni
sezione con gli intervalli del suo tipo; aggiunge i divieti violati e la
distanza stilometrica (stylometry.py).
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import yaml

from nlp.style_profile import config
from nlp.style_profile.parsing import Section, sections_from_markdown

# Sezioni che il profilo copre e su cui ha senso il controllo.
CHECKED_TYPES = ("intro", "corpo", "prima_di_lasciarci", "sguardo")

# Con meno documenti di cosi' l'intervallo e' [min, max], altrimenti [p10, p90].
MIN_DOCS_FOR_PERCENTILES = 8

CONNECTIVE_STARTS = (
    "nel frattempo", "infine", "mentre", "se ", "da una parte", "dall'altra", "dall’altra",
    "dall'altro", "dall’altro", "da un lato", "allo stesso tempo", "nel complesso", "in fondo",
    "ma ", "e ", "anche", "inoltre", "eppure", "intanto", "parlando", "a proposito", "dopo",
    "accanto", "sul fronte", "in questo senso", "allora", "infatti",
)

FEATURE_LABELS = {
    "parole": "parole",
    "frasi": "frasi",
    "paragrafi": "paragrafi (voci per l'elenco)",
    "parole_per_frase": "parole per frase (media)",
    "parole_per_frase_sd": "parole per frase (deviazione)",
    "parole_per_frase_max": "frase più lunga (parole)",
    "quota_frasi_brevi": "quota frasi ≤ 12 parole",
    "quota_frasi_lunghe": "quota frasi ≥ 30 parole",
    "parole_per_paragrafo": "parole per paragrafo/voce",
    "virgole_x1000": "virgole ogni 1000 parole",
    "punto_e_virgola_x1000": "punti e virgola ogni 1000 parole",
    "due_punti_x1000": "due punti ogni 1000 parole",
    "trattini_x1000": "trattini lunghi ogni 1000 parole",
    "parentesi_x1000": "parentesi ogni 1000 parole",
    "virgolette_x1000": "virgolette ogni 1000 parole",
    "domande_x1000": "punti di domanda ogni 1000 parole",
    "quota_soggetto_preverbale": "quota frasi con soggetto prima del verbo",
    "quota_attacco_connettivo": "quota frasi che attaccano con un connettivo",
    "prima_plurale_x1000": "forme di 1ª plurale (ci, noi, -iamo) ogni 1000 parole",
    "seconda_plurale_x1000": "forme di 2ª plurale (vi, voi) ogni 1000 parole",
    "mattr": "varietà lessicale (MATTR, finestra 50)",
    "lunghezza_parola": "lunghezza media delle parole (caratteri)",
    "quota_aggettivi": "quota aggettivi",
    "quota_nomi": "quota nomi comuni",
    "quota_verbi": "quota verbi",
    "corsivi_x100": "titoli in corsivo ogni 100 parole",
}


@lru_cache(maxsize=1)
def get_nlp():
    import spacy

    return spacy.load(config.SPACY_MODEL, disable=["ner"])


def _per_mille(count: int, words: int) -> float:
    return 1000.0 * count / words if words else 0.0


def mattr(tokens: list[str], window: int = 50) -> float:
    """Moving-average type-token ratio: stabile anche su testi brevi."""
    if not tokens:
        return 0.0
    if len(tokens) <= window:
        return len(set(tokens)) / len(tokens)
    ratios = [len(set(tokens[i:i + window])) / window for i in range(len(tokens) - window + 1)]
    return sum(ratios) / len(ratios)


def count_italics(text_md: str) -> int:
    """Conta i tratti in corsivo (*x* o ***x***), esclusi i soli grassetti."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text_md)
    n = 0
    for m in re.finditer(r"(\*{1,3})([^*\n]+?)\1", text):
        if len(m.group(1)) in (1, 3):
            n += 1
    return n


def _starts_with_connective(sentence_text: str) -> bool:
    s = sentence_text.lower().lstrip("“\"«‘'( ")
    return any(s.startswith(c) for c in CONNECTIVE_STARTS)


def _has_preverbal_subject(sent) -> bool:
    root = sent.root
    return any(t.dep_ in ("nsubj", "nsubj:pass") and t.head == root and t.i < root.i for t in sent)


def features(text_plain: str, text_md: str | None = None, n_blocks: int | None = None, nlp=None) -> dict:
    """Metriche di stile di un testo (una sezione)."""
    nlp = nlp or get_nlp()
    doc = nlp(text_plain)
    words = [t for t in doc if t.is_alpha]
    n_words = len(words)
    sents = [s for s in doc.sents if any(t.is_alpha for t in s)]
    sent_lens = [sum(1 for t in s if t.is_alpha) for s in sents]
    blocks = n_blocks if n_blocks is not None else len([b for b in text_plain.split("\n\n") if b.strip()])

    def count(chars: str) -> int:
        return sum(text_plain.count(c) for c in chars)

    first_plur = sum(
        1 for t in doc if "Person=1" in str(t.morph) and "Number=Plur" in str(t.morph) and t.is_alpha
    )
    second_plur = sum(
        1 for t in doc if "Person=2" in str(t.morph) and "Number=Plur" in str(t.morph) and t.is_alpha
    )
    pos = [t.pos_ for t in words]
    md = text_md if text_md is not None else text_plain

    return {
        "parole": n_words,
        "frasi": len(sents),
        "paragrafi": blocks,
        "parole_per_frase": statistics.mean(sent_lens) if sent_lens else 0.0,
        "parole_per_frase_sd": statistics.pstdev(sent_lens) if len(sent_lens) > 1 else 0.0,
        "parole_per_frase_max": max(sent_lens) if sent_lens else 0,
        "quota_frasi_brevi": sum(1 for n in sent_lens if n <= 12) / len(sent_lens) if sent_lens else 0.0,
        "quota_frasi_lunghe": sum(1 for n in sent_lens if n >= 30) / len(sent_lens) if sent_lens else 0.0,
        "parole_per_paragrafo": n_words / blocks if blocks else 0.0,
        "virgole_x1000": _per_mille(count(","), n_words),
        "punto_e_virgola_x1000": _per_mille(count(";"), n_words),
        "due_punti_x1000": _per_mille(count(":"), n_words),
        "trattini_x1000": _per_mille(count("–—"), n_words),
        "parentesi_x1000": _per_mille(count("("), n_words),
        # Coppie di virgolette: si contano le aperture (le dritte valgono mezza).
        "virgolette_x1000": _per_mille(count("“«‘") + count("\"") // 2, n_words),
        "domande_x1000": _per_mille(count("?"), n_words),
        "quota_soggetto_preverbale": sum(_has_preverbal_subject(s) for s in sents) / len(sents) if sents else 0.0,
        "quota_attacco_connettivo": sum(_starts_with_connective(s.text) for s in sents) / len(sents) if sents else 0.0,
        "prima_plurale_x1000": _per_mille(first_plur, n_words),
        "seconda_plurale_x1000": _per_mille(second_plur, n_words),
        "mattr": mattr([t.lower_ for t in words]),
        "lunghezza_parola": statistics.mean(len(t) for t in words) if words else 0.0,
        "quota_aggettivi": pos.count("ADJ") / n_words if n_words else 0.0,
        "quota_nomi": pos.count("NOUN") / n_words if n_words else 0.0,
        "quota_verbi": (pos.count("VERB")) / n_words if n_words else 0.0,
        "corsivi_x100": 100.0 * count_italics(md) / n_words if n_words else 0.0,
    }


def section_features(s: Section, nlp=None) -> dict:
    n_blocks = len(s.items) if s.items and not s.paragraphs else None
    return features(s.text_plain, s.text_md, n_blocks=n_blocks, nlp=nlp)


# ---------------------------------------------------------------------------
# Intervalli
# ---------------------------------------------------------------------------

def _quantile(values: list[float], q: float) -> float:
    v = sorted(values)
    if len(v) == 1:
        return v[0]
    pos = q * (len(v) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def summarize(rows: list[dict]) -> dict:
    out = {}
    for key in rows[0]:
        vals = [float(r[key]) for r in rows]
        out[key] = {
            "min": round(min(vals), 4),
            "p10": round(_quantile(vals, 0.10), 4),
            "mediana": round(_quantile(vals, 0.50), 4),
            "p90": round(_quantile(vals, 0.90), 4),
            "max": round(max(vals), 4),
        }
    return out


def load_corpus(split: str | None = "train") -> list[dict]:
    rows = [json.loads(l) for l in open(config.CORPUS_JSONL, encoding="utf-8")]
    return [r for r in rows if split is None or r["split"] == split]


def build_targets() -> dict:
    nlp = get_nlp()
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in load_corpus("train"):
        if r["section_type"] not in CHECKED_TYPES:
            continue
        s = Section(r["section_type"], r["heading"], r["text_md"], r["text_plain"], r["paragraphs"], r["items"])
        by_type[r["section_type"]].append(section_features(s, nlp=nlp))
    targets = {
        "versione": "stile-v1",
        "corpus": {
            "autore": config.AUTHOR_NAME,
            "hold_out": sorted(config.HOLDOUT_IDS),
            "nota": "Intervalli dalle sezioni di addestramento. Con meno di "
            f"{MIN_DOCS_FOR_PERCENTILES} sezioni si usa [min, max], altrimenti [p10, p90].",
        },
        "sezioni": {
            t: {"n_sezioni": len(rows), "metriche": summarize(rows)} for t, rows in sorted(by_type.items())
        },
    }
    config.TARGETS_YAML.write_text(
        "# Generato da: python -m nlp.style_profile.metrics build. Non modificare a mano.\n"
        + yaml.safe_dump(targets, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return targets


# ---------------------------------------------------------------------------
# Divieti
# ---------------------------------------------------------------------------

def load_divieti() -> list[dict]:
    if not config.DIVIETI_YAML.exists():
        return []
    data = yaml.safe_load(config.DIVIETI_YAML.read_text(encoding="utf-8")) or {}
    return data.get("divieti", [])


def find_divieti(text: str, divieti: list[dict]) -> list[dict]:
    hits = []
    for d in divieti:
        for m in re.finditer(d["pattern"], text, flags=re.IGNORECASE):
            hits.append({
                "pattern": d["pattern"],
                "trovato": m.group(0),
                "motivo": d.get("motivo", ""),
                "livello": d.get("livello", "vietato"),
            })
    return hits


def validate_divieti() -> list[tuple[str, int]]:
    """Un divieto "vietato" che compare nei tuoi testi non e' un tic estraneo:
    va tolto o declassato a "raro" (lo usi, ma quasi mai)."""
    corpus_text = "\n".join(r["text_plain"] for r in load_corpus(None))
    return [(d["pattern"], n) for d in load_divieti()
            if d.get("livello", "vietato") == "vietato"
            and (n := len(re.findall(d["pattern"], corpus_text, flags=re.IGNORECASE))) > 0]


# ---------------------------------------------------------------------------
# Voci di "Prima di lasciarci" che ripetono lo slug dell'URL
# ---------------------------------------------------------------------------

_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
ECHO_FLAG = 5  # parole di fila in comune con lo slug oltre le quali la voce si segnala


def _word_tokens(text: str) -> list[str]:
    # Gli slug di WordPress tolgono l'apostrofo senza spazio: "l'amore" -> "lamore".
    return re.findall(r"[a-zàèéìòù0-9]+", text.lower().replace("’", "").replace("'", ""))


def slug_tokens(url: str) -> list[str]:
    return _word_tokens(url.rstrip("/").rsplit("/", 1)[-1].replace(".html", "").replace("-", " "))


def longest_common_run(a: list[str], b: list[str]) -> int:
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best


def slug_echo(item_md: str) -> int:
    """Parole di fila che la voce ha in comune con lo slug di uno dei suoi link.

    Il titolo dell'opera (in corsivo) e' nello slug per forza: non conta come eco.
    """
    no_titles = re.sub(r"\*[^*]+\*", " ", _MD_LINK.sub(r"\1", item_md))
    plain = _word_tokens(no_titles)
    return max((longest_common_run(plain, slug_tokens(u)) for _, u in _MD_LINK.findall(item_md)), default=0)


def reference_echo() -> dict:
    """Eco delle voci di "Prima di lasciarci" nei tuoi elenchi di addestramento."""
    vals = []
    for r in load_corpus("train"):
        if r["section_type"] == "prima_di_lasciarci":
            vals += [slug_echo(l[2:]) for l in r["text_md"].splitlines() if l.startswith("- ")]
    if not vals:
        return {"n": 0, "quota_4": 0.0, "max": 0}
    return {"n": len(vals), "quota_4": sum(v >= 4 for v in vals) / len(vals), "max": max(vals)}


def check_voci(sections) -> dict | None:
    voci = []
    for s in sections:
        if s.section_type == "prima_di_lasciarci":
            voci += [l[2:] for l in s.text_md.splitlines() if l.startswith("- ")]
    if not voci:
        return None
    echo = [slug_echo(v) for v in voci]
    ref = reference_echo()
    return {
        "voci": [{"testo": strip_md_links(v), "eco": e} for v, e in zip(voci, echo)],
        "quota_4": sum(e >= 4 for e in echo) / len(echo),
        "rif": ref,
        "segnalate": [i for i, e in enumerate(echo) if e >= ECHO_FLAG],
    }


def strip_md_links(text: str) -> str:
    return _MD_LINK.sub(r"\1", text)


# ---------------------------------------------------------------------------
# Controllo
# ---------------------------------------------------------------------------

def _verdict(value: float, stats: dict, n_docs: int) -> str:
    lo, hi = (stats["p10"], stats["p90"]) if n_docs >= MIN_DOCS_FOR_PERCENTILES else (stats["min"], stats["max"])
    if lo <= value <= hi:
        return "ok"
    if stats["min"] <= value <= stats["max"]:
        return "ai margini"
    return "sotto" if value < stats["min"] else "sopra"


def check_text(text_md: str, targets: dict | None = None) -> dict:
    targets = targets or yaml.safe_load(config.TARGETS_YAML.read_text(encoding="utf-8"))
    nlp = get_nlp()
    # L'elenco "## Titoli delle sezioni" (titoli generati senza il testo delle
    # schede) si controlla a parte e non entra tra le sezioni.
    from nlp.style_profile import titles

    titles_block, text_md = titles.extract_titles_block(text_md)
    sections = sections_from_markdown(text_md)
    result = {"sezioni": [], "divieti": [], "stilometria": None}
    for s in sections:
        if s.section_type not in targets["sezioni"]:
            continue
        t = targets["sezioni"][s.section_type]
        feats = section_features(s, nlp=nlp)
        rows = []
        for key, value in feats.items():
            stats = t["metriche"][key]
            rows.append({"metrica": key, "valore": round(float(value), 3), "verdetto": _verdict(value, stats, t["n_sezioni"]), **stats})
        result["sezioni"].append({"tipo": s.section_type, "titolo": s.heading, "metriche": rows, "n_rif": t["n_sezioni"]})
    result["divieti"] = find_divieti("\n".join(s.text_plain for s in sections), load_divieti())
    result["voci"] = check_voci(sections)

    # Titoli delle sezioni del corpo: forma, non metriche per mille parole.
    corpo = [s for s in sections if s.section_type == "corpo" and s.heading]
    entries = titles_block or [{"heading": s.heading, "heading_md": s.heading_md or s.heading} for s in corpo]
    result["titoli"] = None
    if entries and config.TITLES_TARGETS_YAML.exists():
        result["titoli"] = titles.check_titles(entries)

    from nlp.style_profile.stylometry import distance_report

    types = [s.section_type for s in sections]
    result["stilometria"] = distance_report("\n\n".join(s.text_plain for s in sections), types)
    return result


def _fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v)


def report_markdown(result: dict, source: str) -> str:
    out = [f"# Controllo di stile: {source}", ""]
    out += ["Legenda: **ok** dentro l'intervallo abituale; **ai margini** dentro il minimo e il massimo dei tuoi testi; "
            "**sotto**/**sopra** fuori da tutto il corpus. Su sezioni brevi le metriche oscillano molto: "
            "contano gli scarti ripetuti, non il singolo valore.", ""]
    for sec in result["sezioni"]:
        out += [f"## {sec['tipo']}" + (f": {sec['titolo']}" if sec["titolo"] and sec["tipo"] == "corpo" else ""), ""]
        off = [r for r in sec["metriche"] if r["verdetto"] != "ok"]
        out.append(f"{len(sec['metriche']) - len(off)} metriche su {len(sec['metriche'])} nell'intervallo abituale.")
        if sec["n_rif"] < MIN_DOCS_FOR_PERCENTILES:
            out.append(
                f"Solo {sec['n_rif']} sezioni di riferimento: gli intervalli sono stretti e qualche scarto è atteso "
                "anche su un tuo testo vero. Leggi questa sezione come indicazione."
            )
        out.append("")
        out += ["| Metrica | Valore | Abituale (p10–p90) | Corpus (min–max) | Verdetto |", "| --- | --- | --- | --- | --- |"]
        order = {"sotto": 0, "sopra": 0, "ai margini": 1, "ok": 2}
        for r in sorted(sec["metriche"], key=lambda r: order[r["verdetto"]]):
            out.append(
                f"| {FEATURE_LABELS.get(r['metrica'], r['metrica'])} | {_fmt(r['valore'])} | "
                f"{_fmt(r['p10'])}–{_fmt(r['p90'])} | {_fmt(r['min'])}–{_fmt(r['max'])} | {r['verdetto']} |"
            )
        out.append("")
    out += ["## Divieti", ""]
    if result["divieti"]:
        out += [
            f"- «{h['trovato']}»" + (" (raro: nei tuoi testi compare al massimo un paio di volte, mai nelle sezioni di cornice)" if h["livello"] == "raro" else "")
            + f": {h['motivo']}"
            for h in result["divieti"]
        ]
    else:
        out.append("Nessuna formula vietata trovata.")
    out.append("")
    voci = result.get("voci")
    if voci:
        ref = voci["rif"]
        out += ["## Voci di Prima di lasciarci e URL", "",
                "Una voce che ripete lo slug del link non aggiunge niente a chi legge l'URL. "
                f"Nei tuoi elenchi di addestramento ({ref['n']} voci) il {100 * ref['quota_4']:.0f}% delle voci ha 4 o più parole di fila in comune con lo slug, al massimo {ref['max']}. "
                f"Qui: {100 * voci['quota_4']:.0f}%.", "",
                "| Voce | Parole di fila in comune con lo slug |", "| --- | --- |"]
        for i, v in enumerate(voci["voci"]):
            out.append(f"| {v['testo']} | {v['eco']}{' (segnalata)' if i in voci['segnalate'] else ''} |")
        out.append("")
    if result.get("titoli"):
        from nlp.style_profile import titles

        out += ["## Titoli di sezione", "", titles.report_body(result["titoli"]), ""]
    st = result["stilometria"]
    if st:
        out += ["## Distanza stilometrica", "", st["sintesi"], ""]
        out += [
            "| | Distanza dal tuo profilo |",
            "| --- | --- |",
            f"| Testo controllato | {st['testo']:.3f} |",
            f"| Tuoi testi (lascia-uno-fuori), min–max | {st['autore_min']:.3f}–{st['autore_max']:.3f} |",
            f"| Altri autori del sito, p10–mediana | {st['altri_p10']:.3f}–{st['altri_mediana']:.3f} |",
            "",
            st["nota"],
            "",
        ]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="calcola metriche_target.yaml dal corpus di addestramento")
    c = sub.add_parser("check", help="controlla un testo in Markdown")
    c.add_argument("path")
    c.add_argument("--out", help="dove salvare il report (default: giri/<nome>_controllo.md)")
    args = ap.parse_args()

    if args.cmd == "build":
        targets = build_targets()
        for t, v in targets["sezioni"].items():
            print(f"{t}: {v['n_sezioni']} sezioni")
        print(f"-> {config.TARGETS_YAML}")
        for pattern, n in validate_divieti():
            print(f"ATTENZIONE: il divieto {pattern!r} compare {n} volte nei tuoi testi")
        return

    path = Path(args.path)
    result = check_text(path.read_text(encoding="utf-8-sig"))
    report = report_markdown(result, path.name)
    out = Path(args.out) if args.out else config.CHECKS_DIR / f"{path.stem}_controllo.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
