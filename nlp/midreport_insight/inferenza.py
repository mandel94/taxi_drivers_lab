"""
inferenza.py (fase 2)

Dalle osservazioni ai CANDIDATI di insight, con stato (fatto, ipotesi, pattern), confidenza e
confondenti. Il testo finale (fatto, ipotesi, consiglio) lo scrive l'orchestratore e passa da
`validate_insight`. Regole di disciplina: skill td-data-insight.
"""

from __future__ import annotations

import math
import re

CONFIDENCE = ("alta", "media", "bassa")
STATES = ("fatto", "ipotesi", "pattern")
REQUIRED = ("fatto", "ipotesi", "consiglio", "confidenza", "stato", "evidenza")
# Dati inaffidabili, bot e blocchi vanno nella nota sui dati, non negli insight.
_DATA_WORDS = re.compile(r"\b(bot|bloccat\w*|blocco|traffico (?:automatico|sospetto)|inaffidabil\w*)\b", re.I)
_DIM_LABEL = {"format": "formato", "pub_weekday": "giorno di uscita", "pub_hour_bucket": "fascia oraria",
              "age_group": "età dell'articolo", "length_bucket": "lunghezza del titolo",
              "has_question": "titolo con punto interrogativo", "starts_with_number": "titolo che inizia con un numero",
              "has_colon": "titolo con i due punti", "author": "autore"}


def classify_claim(n: int, weeks_with_data: int, weeks_same_direction: int) -> dict:
    """pattern: almeno 3 casi in almeno 3 settimane, stesso verso nei 3/4 delle settimane (due settimane
    sole restano ipotesi: la skill td-data-insight le accetta solo con un meccanismo plausibile)."""
    if weeks_with_data < 2:
        return {"stato": "fatto", "confidenza": "bassa"}
    needed = max(3, math.ceil(0.75 * weeks_with_data))
    if n >= 3 and weeks_same_direction >= needed:
        strong = weeks_with_data >= 4 and weeks_same_direction / weeks_with_data >= 0.8 and n >= 8
        return {"stato": "pattern", "confidenza": "alta" if strong else "media"}
    return {"stato": "ipotesi", "confidenza": "bassa"}


def candidate_insights(obs: dict) -> list[dict]:
    out = []
    for c in obs["categories"]:
        if not c.get("sample_ok") or c.get("direction") not in ("su", "giu"):
            continue
        conf = []
        if (c.get("top1_share_of_category") or 0) >= 0.3:
            conf.append(f"trainato da un solo articolo ('{c['top1_title']}', {c['top1_share_of_category']:.0%} della categoria)")
        if c["n_articles"] < 10:
            conf.append("categoria con pochi articoli")
        out.append({"tipo": "categoria", "categoria": c["category"], "direzione": c["direction"],
                    "fact": c["fact"], "confondenti": conf, "stato": "fatto", "confidenza": "bassa",
                    "peso": abs(math.log(c["share_ratio"])) * math.sqrt(c["users"])})
    for p in obs["patterns"]:
        if not p.get("notable"):
            continue
        cl = classify_claim(p["n"], p["weeks_with_data"], p["weeks_same_direction"])
        conf = []
        if p["dimension"] == "author":
            conf.append("effetto argomento: un autore scrive di temi diversi per periodo, non è un giudizio di merito")
        if p["dimension"] in ("pub_weekday", "pub_hour_bucket"):
            conf.append("i giorni di esposizione cambiano con il giorno di uscita; per gli articoli usciti prima "
                        "della settimana il giorno si confonde con l'età (freschezza)")
        if p["weeks_with_data"] < 3:
            conf.append(f"solo {p['weeks_with_data']} settimane con dati")
        if conf and cl["confidenza"] == "alta":  # con un confondente noto la confidenza non supera "media"
            cl = {**cl, "confidenza": "media"}
        out.append({"tipo": "pattern", "dimensione": p["dimension"], "etichetta": _DIM_LABEL.get(p["dimension"], p["dimension"]),
                    "valore": p["value"], "fact": p["fact"], "confondenti": conf, **cl,
                    "peso": abs(math.log(max(p["median_ratio"], 0.01))) * math.sqrt(p["n"])})
    order = {"pattern": 0, "ipotesi": 1, "fatto": 2}
    return sorted(out, key=lambda c: (order[c["stato"]], -c["peso"]))


def validate_insight(ins: dict) -> list[str]:
    errs = [f"manca il campo {k}" for k in REQUIRED if not ins.get(k)]
    if ins.get("confidenza") and ins["confidenza"] not in CONFIDENCE:
        errs.append(f"confidenza non valida: {ins['confidenza']}")
    if ins.get("stato") and ins["stato"] not in STATES:
        errs.append(f"stato non valido: {ins['stato']}")
    if ins.get("fatto") and not re.search(r"\d", ins["fatto"]):
        errs.append("il fatto non contiene un numero")
    for k in ("fatto", "ipotesi", "consiglio"):
        if ins.get(k) and _DATA_WORDS.search(ins[k]):
            errs.append(f"{k}: dati inaffidabili o bot vanno nella nota sui dati")
    return errs
