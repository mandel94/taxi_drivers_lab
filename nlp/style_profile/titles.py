"""
titles.py

Analisi e controllo dei titoletti di sezione del Trend Radar: quelli che
aprono ogni scheda su un film, una serie o un festival (ad esempio
"*Dead-End Job*, un "lavoro al miele" non è mai troppo dolce").

Con titoli di 4-14 parole le metriche del livello 2 (frasi, virgole per mille
parole) non hanno senso, e una stilometria sulle parole frequenti non regge
(40-60 titoli, 350 parole in tutto). Qui si misura quindi la **forma** del
titoletto:

- struttura: "ancora, lettura" / frase con verbo / sintagma nominale / solo titolo dell'opera;
- cosa e' l'ancora (opera o persona, evento, piattaforma, categoria) e come
  e' fatta la lettura (clausola, infinito, sintagma, preposizione);
- lunghezza, punteggiatura, maiuscole, corsivi, "tra X e Y";
- un punteggio d'insieme (Naive Bayes sulle stesse caratteristiche) che dice
  quanto il titolo somiglia ai titoli dell'autore piu' che ai titoletti degli
  altri autori del sito. Il punteggio e' leave-one-out sui titoli dell'autore.

Comandi (dalla root del progetto):
    .venv\\Scripts\\python.exe -m nlp.style_profile.titles build
    .venv\\Scripts\\python.exe -m nlp.style_profile.titles analyze [--out report.md]
    .venv\\Scripts\\python.exe -m nlp.style_profile.titles check <file.md> [--out report.md]

`check` accetta un file con un titolo per riga (anche "## titolo" o "- titolo",
corsivi in Markdown) oppure un testo con sezioni "## ..." come quello di
`metrics check`.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from nlp.style_profile import config
from nlp.style_profile.parsing import heading_italics_only, sections_from_markdown, strip_md

# ---------------------------------------------------------------------------
# Lessici chiusi per il tipo di ancora. Tutto cio' che non vi rientra e' un
# "nome" (titolo di un'opera, persona, gruppo): classe aperta.
# ---------------------------------------------------------------------------

PIATTAFORMA = re.compile(
    r"\b(netflix|apple tv\+?|prime video|prime|mubi|hbo( max)?|sky|disney\+?|rai cinema|dcu|a24|universal|paramount\+?)\b",
    re.IGNORECASE,
)
EVENTO = re.compile(
    r"\b(venezia|locarno|cannes|berlino|oscar|emmy|golden globe|festival|festa del cinema|festa di roma|mostra|sic|premiazioni|premi|alice nella citt[àa])\b",
    re.IGNORECASE,
)
CATEGORIA = re.compile(
    r"^(le |i |gli |il |l['’])?(serie( tv| e film)?|film( in sala| in uscita)?|trailer|cortometraggi( italiani)?|cortometraggio|interviste|animazione|"
    r"l['’]animazione|cinema|grande cinema|guide|in sala|alcune proposte|teen drama|news|spunti|"
    r"grandi ritorni|estate|approfondimenti|nuovi horror)\b",
    re.IGNORECASE,
)

_CLITICS = ("si", "ci", "ne", "mi", "ti", "vi", "lo", "la", "li", "le", "gli")

_APOS = re.compile(r"([’'])\s+(?=\w)")
_ITALIC_SPAN = re.compile(r"\*([^*]+)\*")
FINALI = ".?!…:"


def normalize_title(text: str) -> str:
    text = _APOS.sub(r"\1", text.replace("\xa0", " "))
    return re.sub(r"\s+", " ", text).strip()


def clean_input(line: str) -> str:
    """Una riga di un file di titoli: toglie "## ", "- ", "1. " e i grassetti."""
    line = re.sub(r"^\s*(#{1,4}|[-*•]|\d+[.)])\s+", "", line)
    return heading_italics_only(line.strip())


def first_separator(text: str) -> tuple[int, str]:
    """Indice e carattere del primo "," o ":" fuori da virgolette e parentesi."""
    depth = 0
    quoted = False
    for i, ch in enumerate(text):
        if ch in "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch in "“«":
            quoted = True
        elif ch in "”»":
            quoted = False
        elif ch in ",:" and depth == 0 and not quoted:
            return i, ch
    return -1, ""


# ---------------------------------------------------------------------------
# Caratteristiche di un titolo
# ---------------------------------------------------------------------------

def _is_finite_root(tok) -> bool:
    return tok.pos_ in ("VERB", "AUX") and "VerbForm=Fin" in str(tok.morph)


def _is_infinitive(tok) -> bool:
    return tok.pos_ in ("VERB", "AUX") and "VerbForm=Inf" in str(tok.morph)


def _reading_type(doc) -> str:
    """Come e' fatta la parte dopo la virgola.

    clausola: ha un verbo finito ("Lamb è l'antieroe dei nostri tempi");
    per_infinito: finale ("per orientarsi"); infinito ("riprendersi la propria musica");
    preposizione ("tra presente e passato", "lungo la strada della memoria", "non solo ...");
    congiunzione ("e la violenza di genere vista al contrario");
    sintagma: gruppo nominale ("un racconto di formazione interrotto").
    """
    if not len(doc):
        return "assente"
    if any(_is_finite_root(t) for t in doc):
        return "clausola"
    first = doc[0]
    if first.lower_ == "per" and len(doc) > 1 and _is_infinitive(doc[1]):
        return "per_infinito"
    if _is_infinitive(first):
        return "infinito"
    if first.pos_ == "ADP" or first.lower_ in ("non", "tra", "lungo", "dopo"):
        return "preposizione"
    if first.pos_ in ("CCONJ", "SCONJ"):
        return "congiunzione"
    return "sintagma"


def _ancora_tipo(ancora: str, in_italics: bool) -> str:
    if not ancora:
        return "assente"
    if PIATTAFORMA.search(ancora):
        return "piattaforma"
    if EVENTO.search(ancora):
        return "evento"
    if CATEGORIA.search(ancora) and not in_italics:
        return "categoria"
    return "nome"


def analyze_titles(items: list[dict], nlp=None) -> list[dict]:
    """Caratteristiche di una lista di titoli.

    Ogni item: {"heading": testo piano, "heading_md": con i corsivi (opzionale)}.
    """
    from nlp.style_profile.metrics import get_nlp

    nlp = nlp or get_nlp()
    plain = [normalize_title(strip_md(i["heading"])) for i in items]
    mds = [normalize_title(i.get("heading_md") or i["heading"]) for i in items]
    docs = list(nlp.pipe(plain))

    segments = []
    for text, md, doc in zip(plain, mds, docs):
        idx, sep = first_separator(text)
        fully_italic = bool(re.fullmatch(r"\*[^*]+\*[.!?…]?", md.strip()))
        if fully_italic:
            struttura, ancora, lettura = "solo_titolo", text, ""
        elif idx > 0:
            struttura, ancora, lettura = "ancora_lettura", text[:idx].strip(), text[idx + 1:].strip()
        else:
            fin = next((t for t in doc if _is_finite_root(t)), None)
            root = next((t for t in doc if t.dep_ == "ROOT"), None)
            if fin is not None:
                # Frase con soggetto prima del verbo (i pronomi clitici restano col verbo).
                cut = fin.i
                while cut > 0 and doc[cut - 1].lower_ in _CLITICS:
                    cut -= 1
                struttura = "frase"
                ancora = text[: doc[cut].idx].strip() if cut > 0 else ""
                lettura = text[doc[cut].idx:].strip()
            elif root is not None and _is_infinitive(root):
                struttura, ancora, lettura = "frase", "", text
            else:
                struttura, ancora, lettura = "sintagma", "", ""
        segments.append((struttura, sep if struttura == "ancora_lettura" else "", ancora, lettura))

    readings = list(nlp.pipe([s[3] if s[0] == "ancora_lettura" else "" for s in segments]))

    out = []
    for text, md, doc, (struttura, sep, ancora, lettura), rdoc in zip(plain, mds, docs, segments, readings):
        words = [t for t in doc if any(c.isalnum() for c in t.text)]
        n_words = len(words)
        ancora_words = len(ancora.split()) if ancora else 0
        spans = _ITALIC_SPAN.findall(md)
        italics = bool(spans)
        ancora_in_italics = bool(ancora) and any(
            normalize_title(s).strip(" ,.").lower() in ancora.lower() for s in spans
        )
        tema = ancora if ancora else text
        tipo = _ancora_tipo(ancora if ancora else (text if struttura == "sintagma" else ""), ancora_in_italics)
        if struttura == "sintagma" and tipo == "nome":
            tipo = "altro"

        # Maiuscole che non dovrebbero esserci: parole comuni con l'iniziale
        # maiuscola dopo la prima, fuori dall'ancora (che puo' essere un titolo).
        start_char = len(ancora) + 1 if struttura in ("ancora_lettura", "frase") else 0
        interne = 0
        for t in doc:
            if struttura == "solo_titolo":
                break  # il titolo di un'opera ha la sua grafia
            if t.idx < start_char or t.i == 0 or not t.is_alpha or len(t.text) < 2:
                continue
            if t.text[0].isupper() and not t.text.isupper() and t.pos_ not in ("PROPN",):
                interne += 1

        first = doc[0] if len(doc) else None
        fin_tok = next((t for t in doc if _is_finite_root(t)), None)
        finale = text[-1] if text and text[-1] in FINALI else "nessuno"
        if text.endswith("…") or text.endswith("..."):
            finale = "…"
        out.append({
            "titolo": text,
            "titolo_md": md,
            "struttura": struttura,
            "separatore": sep or "",
            "ancora": ancora,
            "lettura": lettura,
            "ancora_tipo": tipo,
            "lettura_tipo": _reading_type(rdoc) if struttura == "ancora_lettura" else "assente",
            "parole": n_words,
            "ancora_parole": ancora_words,
            "lettura_parole": len(lettura.split()) if lettura else 0,
            "caratteri_per_parola": statistics.mean(len(t.text) for t in words) if words else 0.0,
            "ancora_in_corsivo": int(ancora_in_italics),
            "ha_corsivo": int(italics),
            "ha_tra": int(bool(re.search(r"(?<!\w)tra(?!\w)", text, re.IGNORECASE))),
            # "*Wild Horse Nine* porta il golpe..." riassume la trama; con un'opera
            # come soggetto il verbo dei titoli e' quasi sempre "è" (definizione o giudizio).
            "opera_verbo_azione": int(
                struttura == "frase" and tipo == "nome" and bool(ancora)
                and fin_tok is not None and fin_tok.lemma_ != "essere"
            ),
            # Per "ancora, lettura" conta solo la lettura: un titolo di opera puo'
            # contenere un verbo ("Se domani non torno").
            "ha_verbo_finito": int(any(_is_finite_root(t) for t in (rdoc if struttura == "ancora_lettura" else doc))),
            "inizia_articolo": int(bool(first is not None and first.pos_ == "DET")),
            "finale": finale,
            "due_punti": int(":" in text),
            "parentesi": int("(" in text),
            "virgolette": int(any(c in text for c in "“”«»\"")),
            "virgolette_dritte": int('"' in text),
            "numeri": int(any(t.like_num or t.text.isdigit() for t in doc)),
            "puntini": int("…" in text or "..." in text),
            "maiuscole_interne": interne,
        })
    return out


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------

def _eligible(row: dict) -> bool:
    return row["section_type"] == "corpo" and bool(row.get("heading")) and row["published"] >= config.TITLES_FROM_DATE


def load_author_titles(split: str | None = "train") -> list[dict]:
    rows = [json.loads(l) for l in open(config.CORPUS_JSONL, encoding="utf-8")]
    items = []
    for r in rows:
        if not _eligible(r) or (split and r["split"] != split):
            continue
        items.append({
            "article_id": r["article_id"], "published": r["published"], "split": r["split"],
            "posizione": r["section_index"], "heading": r["heading"], "heading_md": r.get("heading_md") or r["heading"],
        })
    # posizione nel corpo: 1 = prima sezione tematica
    by_art: dict[int, list[dict]] = defaultdict(list)
    for it in items:
        by_art[it["article_id"]].append(it)
    for lst in by_art.values():
        for k, it in enumerate(sorted(lst, key=lambda x: x["posizione"]), 1):
            it["posizione"], it["n_sezioni"] = k, len(lst)
    return items


def load_other_titles() -> list[dict]:
    if not config.OTHERS_TITLES_JSONL.exists():
        return []
    return [json.loads(l) for l in open(config.OTHERS_TITLES_JSONL, encoding="utf-8")]


def author_features(split: str | None = "train") -> list[dict]:
    items = load_author_titles(split)
    feats = analyze_titles(items)
    for it, f in zip(items, feats):
        f.update({k: it[k] for k in ("article_id", "published", "split", "posizione", "n_sezioni")})
    return feats


# ---------------------------------------------------------------------------
# Intervalli
# ---------------------------------------------------------------------------

NUMERIC = ["parole", "ancora_parole", "lettura_parole", "caratteri_per_parola", "maiuscole_interne"]
BINARY = ["ancora_in_corsivo", "ha_corsivo", "ha_tra", "ha_verbo_finito", "inizia_articolo", "due_punti",
          "parentesi", "virgolette", "numeri", "puntini", "opera_verbo_azione"]
CATEGORICAL = ["struttura", "ancora_tipo", "lettura_tipo", "finale"]
MIN_FOR_PERCENTILES = 20


def _quantile(values: list[float], q: float) -> float:
    v = sorted(values)
    if len(v) == 1:
        return v[0]
    pos = q * (len(v) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(v) - 1)
    return v[lo] + (v[hi] - v[lo]) * (pos - lo)


def summarize_titles(feats: list[dict]) -> dict:
    n = len(feats)
    out: dict = {"n_titoli": n, "numeriche": {}, "binarie": {}, "categoriche": {}}
    for k in NUMERIC:
        vals = [float(f[k]) for f in feats]
        out["numeriche"][k] = {
            "min": round(min(vals), 3), "p10": round(_quantile(vals, 0.10), 3),
            "mediana": round(_quantile(vals, 0.5), 3), "p90": round(_quantile(vals, 0.90), 3),
            "max": round(max(vals), 3),
        }
    for k in BINARY:
        out["binarie"][k] = round(sum(f[k] for f in feats) / n, 4)
    for k in CATEGORICAL:
        c = Counter(f[k] for f in feats)
        out["categoriche"][k] = {cat: {"n": c[cat], "quota": round(c[cat] / n, 4)} for cat, _ in c.most_common()}
    return out


# ---------------------------------------------------------------------------
# Punteggio: Naive Bayes sulle caratteristiche di forma
# ---------------------------------------------------------------------------

def _bin_words(n: int) -> str:
    for hi, label in ((3, "<=3"), (5, "4-5"), (7, "6-7"), (9, "8-9"), (12, "10-12")):
        if n <= hi:
            return label
    return "13+"


def _bin_reading(n: int) -> str:
    for hi, label in ((0, "0"), (3, "1-3"), (5, "4-5"), (7, "6-7")):
        if n <= hi:
            return label
    return "8+"


def model_features(f: dict) -> dict[str, str]:
    """Caratteristiche discretizzate per il Naive Bayes. Niente argomenti ne' lessico."""
    return {
        "parole": _bin_words(f["parole"]),
        "lettura_parole": _bin_reading(f["lettura_parole"]),
        "struttura": f["struttura"],
        "ancora_tipo": f["ancora_tipo"],
        "lettura_tipo": f["lettura_tipo"],
        "finale": f["finale"],
        "ha_tra": str(f["ha_tra"]),
        "inizia_articolo": str(f["inizia_articolo"]),
        "ha_verbo_finito": str(f["ha_verbo_finito"]),
        "virgolette": str(f["virgolette"]),
        "parentesi": str(f["parentesi"]),
        "due_punti": str(f["due_punti"]),
        "maiuscole_interne": "0" if f["maiuscole_interne"] == 0 else "1+",
        "ancora_in_corsivo": str(f["ancora_in_corsivo"]),
    }


class NaiveBayes:
    """Log-rapporto di verosimiglianza autore / altri, con lisciatura di Laplace."""

    ALPHA = 1.0

    def __init__(self, author: list[dict], others: list[dict]):
        self.n = {"a": len(author), "o": len(others)}
        self.counts = {"a": defaultdict(Counter), "o": defaultdict(Counter)}
        self.cats: dict[str, set] = defaultdict(set)
        for cls, rows in (("a", author), ("o", others)):
            for f in rows:
                for k, v in model_features(f).items():
                    self.counts[cls][k][v] += 1
                    self.cats[k].add(v)

    def contributions(self, f: dict, leave_out: str | None = None) -> dict[str, float]:
        mf = model_features(f)
        out = {}
        for k, v in mf.items():
            K = len(self.cats[k] | {v})
            ca = self.counts["a"][k][v] - (1 if leave_out == "a" else 0)
            co = self.counts["o"][k][v] - (1 if leave_out == "o" else 0)
            na = self.n["a"] - (1 if leave_out == "a" else 0)
            no = self.n["o"] - (1 if leave_out == "o" else 0)
            pa = (ca + self.ALPHA) / (na + self.ALPHA * K)
            po = (co + self.ALPHA) / (no + self.ALPHA * K)
            out[k] = math.log(pa / po)
        return out

    def score(self, f: dict, leave_out: str | None = None) -> float:
        return sum(self.contributions(f, leave_out).values())


def auc(pos: list[float], neg: list[float]) -> float:
    if not pos or not neg:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def build_model(author: list[dict] | None = None, others: list[dict] | None = None):
    author = author if author is not None else author_features("train")
    if others is None:
        others = analyze_titles(load_other_titles())
    return NaiveBayes(author, others), author, others


def discrimination(model: NaiveBayes, author: list[dict], others: list[dict]) -> dict:
    a = [model.score(f, "a") for f in author]
    o = [model.score(f, "o") for f in others]
    return {
        "auc_loo": auc(a, o),
        "autore": {"p10": _quantile(a, 0.1), "mediana": _quantile(a, 0.5), "p90": _quantile(a, 0.9), "min": min(a), "max": max(a)},
        "altri": {"p10": _quantile(o, 0.1), "mediana": _quantile(o, 0.5), "p90": _quantile(o, 0.9), "min": min(o), "max": max(o)},
        "n_autore": len(a), "n_altri": len(o),
    }


def feature_auc(author: list[dict], others: list[dict]) -> list[tuple[str, float, float, float]]:
    """Per ogni caratteristica numerica o binaria: media autore, media altri, AUC."""
    rows = []
    for k in NUMERIC + BINARY:
        a = [float(f[k]) for f in author]
        o = [float(f[k]) for f in others]
        rows.append((k, statistics.mean(a), statistics.mean(o), auc(a, o)))
    return sorted(rows, key=lambda r: -abs(r[3] - 0.5))


# ---------------------------------------------------------------------------
# Build, analisi, controllo
# ---------------------------------------------------------------------------

def recent_regime(author: list[dict]) -> dict:
    """Mix di strutture e ancore negli ultimi numeri, dove il formato si e' stabilizzato."""
    recent = [f for f in author if f["published"] >= config.TITLES_RECENT_FROM]
    by_art: dict[int, list[dict]] = defaultdict(list)
    for f in recent:
        by_art[f["article_id"]].append(f)
    share_nome = [sum(f["ancora_tipo"] == "nome" for f in v) / len(v) for v in by_art.values()]
    share_ancora = [sum(f["struttura"] == "ancora_lettura" for f in v) / len(v) for v in by_art.values()]
    nome = [f for f in recent if f["ancora_tipo"] == "nome"]
    return {
        "da": config.TITLES_RECENT_FROM,
        "n_articoli": len(by_art),
        "n_titoli": len(recent),
        "titoli_per_articolo": sorted(len(v) for v in by_art.values()),
        "quota_ancora_nome_per_articolo": {"min": round(min(share_nome), 3), "max": round(max(share_nome), 3)},
        "quota_ancora_lettura_per_articolo": {"min": round(min(share_ancora), 3), "max": round(max(share_ancora), 3)},
        "ancora_nome_in_corsivo": round(sum(f["ancora_in_corsivo"] for f in nome) / len(nome), 3) if nome else None,
        "categoriche": {
            k: {cat: round(v / len(recent), 3) for cat, v in Counter(f[k] for f in recent).most_common()}
            for k in ("struttura", "ancora_tipo", "lettura_tipo")
        },
    }


def build_targets() -> dict:
    author = author_features("train")
    model, author, others = build_model(author)
    disc = discrimination(model, author, others)
    targets = {
        "versione": "titoli-v1",
        "corpus": {
            "autore": config.AUTHOR_NAME,
            "da": config.TITLES_FROM_DATE,
            "hold_out": sorted(config.HOLDOUT_IDS),
            "n_altri_titoletti": len(others),
        },
        "titoli": summarize_titles(author),
        "formato_attuale": recent_regime(author),
        "discriminazione": {
            "auc_loo": round(disc["auc_loo"], 3),
            "autore": {k: round(v, 3) for k, v in disc["autore"].items()},
            "altri": {k: round(v, 3) for k, v in disc["altri"].items()},
        },
    }
    config.TITLES_TARGETS_YAML.write_text(
        "# Generato da: python -m nlp.style_profile.titles build. Non modificare a mano.\n"
        + yaml.safe_dump(targets, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return targets


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def check_titles(entries: list[dict], targets: dict | None = None) -> dict:
    """Controlla un insieme di titoli (quelli di un articolo)."""
    targets = targets or yaml.safe_load(config.TITLES_TARGETS_YAML.read_text(encoding="utf-8"))
    t = targets["titoli"]
    model, author, others = build_model()
    disc = discrimination(model, author, others)
    feats = analyze_titles(entries)

    from nlp.style_profile.metrics import find_divieti, load_divieti

    divieti = load_divieti()
    n_corpus = t["n_titoli"]
    marks = {
        "due_punti": "due punti", "parentesi": "parentesi", "virgolette": "virgolette",
        "puntini": "puntini di sospensione",
        "opera_verbo_azione": "opera o persona soggetto di un verbo d'azione (con un'opera il verbo è «è»; altrimenti «Ancora, lettura»)",
    }

    rows = []
    for f in feats:
        issues = []
        num = t["numeriche"]
        is_work_title = f["struttura"] == "solo_titolo"  # il titolo di un'opera ha la sua grafia e lunghezza
        if not is_work_title:
            for k in ("parole", "lettura_parole"):
                lo, hi = (num[k]["p10"], num[k]["p90"]) if n_corpus >= MIN_FOR_PERCENTILES else (num[k]["min"], num[k]["max"])
                if f[k] < num[k]["min"] or f[k] > num[k]["max"]:
                    issues.append(f"{k.replace('_', ' ')} {f[k]:.4g}: fuori da tutto il corpus ({num[k]['min']:g}-{num[k]['max']:g})")
                elif f[k] < lo or f[k] > hi:
                    issues.append(f"{k.replace('_', ' ')} {f[k]:.4g}: ai margini (abituale {lo:g}-{hi:g})")
            if f["maiuscole_interne"] > num["maiuscole_interne"]["max"]:
                issues.append(f"{f['maiuscole_interne']} parole comuni con la maiuscola (dopo la prima parola i titoli sono in minuscolo)")
            if f["finale"] == ".":
                issues.append("punto finale: i titoli non lo hanno")
        for k in CATEGORICAL:
            if f[k] not in t["categoriche"][k] and not (is_work_title and k == "finale"):
                issues.append(f"{k.replace('_', ' ')} «{f[k]}» mai visto nei tuoi titoli")
        if f["virgolette_dritte"]:
            issues.append("virgolette dritte (nei tuoi titoli sono “ ”)")
        if re.search(r"\s[-–—]\s", re.sub(r"\*[^*]+\*", "", f["titolo_md"])):
            issues.append("trattino con spazi come separatore (nei tuoi titoli c'è solo dentro il titolo di un'opera)")
        for k, label in marks.items():
            share = t["binarie"][k]
            if f[k] and share <= 0.05:
                n = round(share * n_corpus)
                quanti = "mai" if n == 0 else f"solo {n} {'titolo' if n == 1 else 'titoli'} su {n_corpus}"
                issues.append(f"{label}: {quanti} nei tuoi titoli")
        for h in find_divieti(f["titolo"], divieti):
            issues.append(f"formula da evitare «{h['trovato']}» ({h['livello']}): {h['motivo']}")
        contrib = model.contributions(f)
        score = sum(contrib.values())
        worst = sorted(contrib.items(), key=lambda kv: kv[1])[:2]
        rows.append({**f, "score": score, "issues": issues,
                     "pesi_negativi": [(k, v) for k, v in worst if v < -0.3]})
    scores = [r["score"] for r in rows]
    struct = Counter(r["struttura"] for r in rows)

    # Controlli sull'insieme: quanti titoli, e quanti partono dal nome dell'opera.
    insieme = []
    reg = targets.get("formato_attuale")
    if reg and rows:
        lo, hi = min(reg["titoli_per_articolo"]), max(reg["titoli_per_articolo"])
        if not lo <= len(rows) <= hi:
            insieme.append(f"{len(rows)} titoli: negli ultimi {reg['n_articoli']} numeri erano tra {lo} e {hi}")
        # Con 4-6 titoli per numero una quota si muove a scatti di un titolo:
        # la tolleranza e' di un titolo oltre il minimo e il massimo osservati.
        tol = 1 / len(rows)
        quota_nome = sum(r["ancora_tipo"] == "nome" for r in rows) / len(rows)
        rng = reg["quota_ancora_nome_per_articolo"]
        if quota_nome < rng["min"] - tol - 1e-9 or quota_nome > rng["max"] + tol + 1e-9:
            insieme.append(
                f"{_pct(quota_nome)} dei titoli parte dal nome di un'opera o di una persona: "
                f"negli ultimi {reg['n_articoli']} numeri tra {_pct(rng['min'])} e {_pct(rng['max'])}"
            )
        quota_al = sum(r["struttura"] == "ancora_lettura" for r in rows) / len(rows)
        rng = reg["quota_ancora_lettura_per_articolo"]
        if quota_al < rng["min"] - tol - 1e-9 or quota_al > rng["max"] + tol + 1e-9:
            insieme.append(
                f"{_pct(quota_al)} dei titoli ha la forma «ancora, lettura»: "
                f"negli ultimi {reg['n_articoli']} numeri tra {_pct(rng['min'])} e {_pct(rng['max'])}"
            )
    # Titoli troppo lunghi: il 90° percentile dei titoli dell'autore e' 9 parole.
    p90 = t["numeriche"]["parole"]["p90"]
    lunghi = [r for r in rows if r["struttura"] != "solo_titolo" and r["parole"] > p90]
    if len(lunghi) >= 2 and len(lunghi) / len(rows) >= 0.5:
        insieme.append(f"{len(lunghi)} titoli su {len(rows)} superano le {p90:g} parole (il 90° percentile dei tuoi titoli)")
    duplicati = [k for k, v in Counter(r["titolo"].lower() for r in rows).items() if v > 1]
    if duplicati:
        insieme.append("titoli duplicati: " + ", ".join(duplicati))
    result = {
        "titoli": rows,
        "n": len(rows),
        "punteggio_medio": statistics.mean(scores) if scores else float("nan"),
        "strutture": dict(struct),
        "duplicati": duplicati,
        "insieme": insieme,
        "riferimento": disc,
    }
    return result


def report_markdown(result: dict, source: str) -> str:
    return "\n".join([f"# Controllo dei titoli di sezione: {source}", "", report_body(result)])


def report_body(result: dict) -> str:
    ref = result["riferimento"]
    out: list[str] = []
    a, o = ref["autore"], ref["altri"]
    out += [
        f"Il punteggio è un log-rapporto di verosimiglianza: sopra 0 il titolo somiglia ai tuoi titoli più che ai titoletti degli altri autori del sito. "
        f"Riferimento: tuoi titoli (leave-one-out) mediana {a['mediana']:.1f}, p10 {a['p10']:.1f}; titoletti degli altri mediana {o['mediana']:.1f}, p90 {o['p90']:.1f}. "
        f"Separabilità misurata (AUC leave-one-out): {ref['auc_loo']:.2f}.",
        "",
        "| # | Titolo | Struttura | Ancora | Lettura | Parole | Punteggio | Segnalazioni |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for i, r in enumerate(result["titoli"], 1):
        flag = "; ".join(r["issues"]) or "—"
        out.append(
            f"| {i} | {r['titolo_md']} | {r['struttura'].replace('_', ' ')} | {r['ancora_tipo']} | {r['lettura_tipo']} | "
            f"{r['parole']} | {r['score']:+.1f} | {flag} |"
        )
    out.append("")
    verdict = "nell'area dei tuoi titoli" if result["punteggio_medio"] >= a["p10"] else (
        "tra i tuoi titoli e quelli degli altri autori" if result["punteggio_medio"] > o["p90"] else "più vicino ai titoletti degli altri autori")
    out += [f"Punteggio medio del gruppo: {result['punteggio_medio']:+.1f}, {verdict}.", ""]
    if result["insieme"]:
        out += ["Segnalazioni sull'insieme:", ""] + [f"- {s}" for s in result["insieme"]] + [""]
    else:
        out += ["Insieme: numero di titoli e quota di titoli «ancora, lettura» come negli ultimi numeri.", ""]
    low = [r for r in result["titoli"] if r["pesi_negativi"]]
    if low:
        out += ["Caratteristiche che pesano contro, per titolo:", ""]
        for r in low:
            out.append(f"- «{r['titolo']}»: " + ", ".join(f"{k.replace('_', ' ')} ({v:+.1f})" for k, v in r["pesi_negativi"]))
        out.append("")
    out += ["Con 4-6 titoli per articolo il gruppo è piccolo: contano le segnalazioni ripetute, non il singolo punteggio.", ""]
    return "\n".join(out)


_TITLES_BLOCK = re.compile(r"^#{1,4}\s*titoli( delle sezioni| di sezione)?\s*:?\s*$", re.IGNORECASE | re.MULTILINE)


def extract_titles_block(text: str) -> tuple[list[dict] | None, str]:
    """Estrae da un testo l'elenco sotto "## Titoli delle sezioni" (una riga per
    titolo, anche numerata o puntata). Restituisce i titoli e il testo senza il blocco."""
    text = text.lstrip("﻿")  # i file salvati da Windows possono avere il BOM
    m = _TITLES_BLOCK.search(text)
    if not m:
        return None, text
    nxt = re.search(r"^#{1,4}\s+", text[m.end():], flags=re.MULTILINE)
    end = m.end() + nxt.start() if nxt else len(text)
    entries = []
    for line in text[m.end():end].splitlines():
        if line.strip():
            md = clean_input(line)
            entries.append({"heading": strip_md(md), "heading_md": md})
    return entries, text[: m.start()] + text[end:]


def entries_from_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8-sig")
    block, text = extract_titles_block(text)
    if block:
        return block
    if re.search(r"^#{2,4}\s+", text, flags=re.MULTILINE):
        secs = [s for s in sections_from_markdown(text) if s.section_type == "corpo" and s.heading]
        if secs:
            return [{"heading": s.heading, "heading_md": s.heading_md or s.heading} for s in secs]
    out = []
    for line in text.splitlines():
        if line.strip() and not line.startswith("# "):
            md = clean_input(line)
            out.append({"heading": strip_md(md), "heading_md": md})
    return out


def analyze_report() -> str:
    """Rapporto d'analisi sui titoli di addestramento (per il documento di metodo)."""
    author = author_features("train")
    model, author, others = build_model(author)
    disc = discrimination(model, author, others)
    summ = summarize_titles(author)
    out = ["# Analisi dei titoli di sezione", "",
           f"{summ['n_titoli']} titoli di addestramento (dal {config.TITLES_FROM_DATE}), {len(others)} titoletti di altri autori.", ""]
    for k in CATEGORICAL:
        out += [f"## {k}", "", "| Valore | Titoli | Quota |", "| --- | --- | --- |"]
        for cat, v in summ["categoriche"][k].items():
            out.append(f"| {cat} | {v['n']} | {_pct(v['quota'])} |")
        out.append("")
    out += ["## Numeriche", "", "| Misura | min | p10 | mediana | p90 | max |", "| --- | --- | --- | --- | --- | --- |"]
    for k, v in summ["numeriche"].items():
        out.append(f"| {k} | {v['min']:g} | {v['p10']:g} | {v['mediana']:g} | {v['p90']:g} | {v['max']:g} |")
    out += ["", "## Binarie (quota di titoli)", "", "| Tratto | Quota |", "| --- | --- |"]
    for k, v in summ["binarie"].items():
        out.append(f"| {k} | {_pct(v)} |")
    reg = recent_regime(author)
    out += ["", f"## Formato attuale (dal {reg['da']}: {reg['n_articoli']} numeri, {reg['n_titoli']} titoli)", "",
            f"- Titoli per numero: {', '.join(map(str, reg['titoli_per_articolo']))}.",
            f"- Quota di titoli con ancora «nome» per numero: {_pct(reg['quota_ancora_nome_per_articolo']['min'])}-{_pct(reg['quota_ancora_nome_per_articolo']['max'])}.",
            f"- Quota di titoli «ancora, lettura» per numero: {_pct(reg['quota_ancora_lettura_per_articolo']['min'])}-{_pct(reg['quota_ancora_lettura_per_articolo']['max'])}.",
            f"- Titolo dell'opera in corsivo nel titoletto: {_pct(reg['ancora_nome_in_corsivo'])} dei casi.", ""]
    for k, v in reg["categoriche"].items():
        out.append(f"- {k}: " + ", ".join(f"{cat} {_pct(q)}" for cat, q in v.items()))
    out += ["", "## Cosa distingue i tuoi titoli dai titoletti degli altri autori", "",
            "| Tratto | Media autore | Media altri | AUC |", "| --- | --- | --- | --- |"]
    for k, ma, mo, a in feature_auc(author, others):
        out.append(f"| {k} | {ma:.2f} | {mo:.2f} | {a:.2f} |")
    out += ["", f"AUC del punteggio d'insieme (leave-one-out): {disc['auc_loo']:.2f}.", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="calcola metriche_titoli.yaml")
    a = sub.add_parser("analyze", help="rapporto d'analisi sui titoli di addestramento")
    a.add_argument("--out")
    c = sub.add_parser("check", help="controlla un insieme di titoli")
    c.add_argument("path")
    c.add_argument("--out")
    args = ap.parse_args()

    if args.cmd == "build":
        t = build_targets()
        print(f"{t['titoli']['n_titoli']} titoli; AUC leave-one-out {t['discriminazione']['auc_loo']}")
        print(f"-> {config.TITLES_TARGETS_YAML}")
    elif args.cmd == "analyze":
        report = analyze_report()
        if args.out:
            Path(args.out).write_text(report, encoding="utf-8")
        print(report)
    else:
        path = Path(args.path)
        result = check_titles(entries_from_file(path))
        report = report_markdown(result, path.name)
        out = Path(args.out) if args.out else config.CHECKS_DIR / f"{path.stem}_titoli.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(report)
        print(f"\n-> {out}")


if __name__ == "__main__":
    main()
