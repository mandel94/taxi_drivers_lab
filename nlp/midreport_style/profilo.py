"""Calcola il profilo di stile dei midreport inviati a Sandra (corpus/*.txt).

Uso: python nlp/midreport_style/profilo.py  -> stampa un riepilogo e scrive profilo_dati.json
"""
from __future__ import annotations

import json
import re
import statistics as st
from collections import Counter
from pathlib import Path

QUI = Path(__file__).resolve().parent
RE_CAT = re.compile(r"^\*([^*]+):\*\s*$")
RE_ITEM = re.compile(r"^•\s")
RE_NOTA = re.compile(r"^Nota:")
RE_SINT = re.compile(r"^\s+-\s")


def leggi(path: Path) -> dict:
    testo = path.read_text(encoding="utf-8")
    testa, _, corpo = testo.partition("\n\n")
    meta = dict(r.split(": ", 1) for r in testa.splitlines() if ": " in r)
    # unisce le righe a capo dentro lo stesso paragrafo
    blocchi = [re.sub(r"\s*\n\s*", " ", b).strip() for b in corpo.split("\n\n")]
    righe = [b for b in blocchi if b]
    return {"meta": meta, "blocchi": righe, "raw": corpo}


def analizza(d: dict) -> dict:
    cats, voci, note, sint = [], Counter(), 0, 0
    corrente = None
    for b in d["blocchi"]:
        m = RE_CAT.match(b)
        if m:
            corrente = m.group(1)
            cats.append(corrente)
            continue
        if RE_ITEM.match(b) and corrente:
            voci[corrente] += 1
        elif RE_NOTA.match(b):
            note += 1
    # puntini della sintesi: righe "   - " nel testo grezzo
    sint = len(re.findall(r"^\s+-\s", d["raw"], re.M))
    parole_sint = 0
    m = re.search(r"In sintesi:?\s*(.*?)\n\s*\*[^*\n]+:\*\s*\n", d["raw"], re.S)
    if m:
        parole_sint = len(m.group(1).split())
    righe = d["raw"].splitlines()
    chiusura = [r for r in righe if re.match(r"^(Buon|Una buona|Grazie|A presto|Un saluto)", r.strip())]
    return {
        "categorie": cats,
        "voci_per_cat": dict(voci),
        "note": note,
        "punti_sintesi": sint,
        "parole_sintesi": parole_sint,
        "parole_totali": len(d["raw"].split()),
        "saluto": d["blocchi"][0] if d["blocchi"] else "",
        "apertura": d["blocchi"][1] if len(d["blocchi"]) > 1 else "",
        "chiusura": chiusura[:1],
        "ha_grafico": "newplot" in d["raw"] or "trend delle visualizzazioni" in d["raw"],
        "allegati": d["meta"].get("ATTACHMENTS", ""),
        "to": d["meta"].get("TO", ""),
        "oggetto": d["meta"].get("SUBJECT", ""),
    }


def main() -> None:
    out = {}
    for p in sorted((QUI / "corpus").glob("*.txt")):
        out[p.name] = analizza(leggi(p))
    (QUI / "profilo_dati.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    tutti = list(out.values())
    print("report:", len(tutti))
    print("parole totali mediana:", st.median(t["parole_totali"] for t in tutti))
    print("punti sintesi (per report):", [t["punti_sintesi"] for t in tutti])
    print("parole sintesi (per report):", [t["parole_sintesi"] for t in tutti])
    print("note per report:", [t["note"] for t in tutti])
    print("grafico:", [t["ha_grafico"] for t in tutti].count(True), "/", len(tutti))
    print("n categorie:", [len(t["categorie"]) for t in tutti])
    freq = Counter(c for t in tutti for c in t["categorie"])
    print("categorie:", dict(freq.most_common()))
    print("voci per categoria (distribuzione):", Counter(v for t in tutti for v in t["voci_per_cat"].values()))
    print("saluti:", Counter(t["saluto"] for t in tutti).most_common(5))
    print("chiusure:", Counter(tuple(t["chiusura"]) for t in tutti).most_common(5))
    print("allegati:", Counter(re.sub(r"\d+", "N", t["allegati"]) for t in tutti).most_common(4))
    print("oggetti:", [t["oggetto"][:60] for t in tutti][-3:])
    print("ordine categorie ultimo:", tutti[-1]["categorie"])
    print("ordine categorie penultimo:", tutti[-2]["categorie"])


if __name__ == "__main__":
    main()
