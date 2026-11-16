"""
lezioni.py

Il circuito di apprendimento della leggibilita':
  - ogni testo controllato (`garantisci`) e ogni riscrittura (`registra_riscrittura`) finiscono in
    dati/eventi.jsonl: punteggio prima e dopo, problemi, azioni;
  - ogni feedback dell'utente (`feedback`) finisce nello stesso registro e, se indica un termine
    difficile, entra nel glossario (dati/glossario.json), che da quel momento il controllo segnala;
  - `aggiorna_documento` rigenera il documento centrale docs/leggibilita.md da regole.md, glossario
    ed eventi: regole, problemi piu' frequenti, esempi prima e dopo, feedback, glossario.
"""

from __future__ import annotations

import collections
import datetime as dt
import json
from pathlib import Path

from nlp.leggibilita import ciclo
from nlp.leggibilita import misura as m

ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = ROOT / "docs" / "leggibilita.md"
REGOLE_PATH = Path(__file__).resolve().parent / "regole.md"


def _dir(dati_dir) -> Path:
    return Path(dati_dir) if dati_dir else m.dati_dir()


def _append(dati_dir, event: dict) -> None:
    d = _dir(dati_dir)
    d.mkdir(parents=True, exist_ok=True)
    event = {"ts": dt.datetime.now().isoformat(timespec="seconds"), **event}
    with open(d / "eventi.jsonl", "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def eventi(dati_dir=None) -> list[dict]:
    p = _dir(dati_dir) / "eventi.jsonl"
    if not p.exists():
        return []
    return [json.loads(r) for r in p.read_text(encoding="utf-8").splitlines() if r.strip()]


def garantisci(text: str, origine: str = "altro", dati_dir=None, glossario=None) -> dict:
    """migliora() piu' registrazione dell'evento. Restituisce il risultato di migliora()."""
    glossario = m.carica_glossario(_dir(dati_dir) / "glossario.json") if glossario is None else glossario
    before = m.check(text, glossario)
    res = ciclo.migliora(text, glossario)
    after = m.check(res["testo"], glossario)
    _append(dati_dir, {"tipo": "testo", "origine": origine, "prima": text,
                       "dopo": res["testo"] if res["testo"] != text else None, "ok": res["ok"],
                       "gulpease_prima": before["gulpease"], "gulpease_dopo": after["gulpease"],
                       "problemi_prima": before["problems"], "problemi_dopo": after["problems"],
                       "azioni": [a for it in res["iterazioni"] for a in it["azioni"]]})
    return res


def registra_riscrittura(prima: str, dopo: str, origine: str = "altro", dati_dir=None, glossario=None) -> dict:
    """Una riscrittura fatta da chi scrive (non meccanica): serve per gli esempi prima e dopo."""
    glossario = m.carica_glossario(_dir(dati_dir) / "glossario.json") if glossario is None else glossario
    b, a = m.check(prima, glossario), m.check(dopo, glossario)
    ev = {"tipo": "riscrittura", "origine": origine, "prima": prima, "dopo": dopo, "ok": a["ok"],
          "gulpease_prima": b["gulpease"], "gulpease_dopo": a["gulpease"],
          "problemi_prima": b["problems"], "problemi_dopo": a["problems"], "azioni": []}
    _append(dati_dir, ev)
    return ev


def feedback(testo: str, termine: str | None = None, semplice: str | None = None,
             origine: str = "utente", dati_dir=None) -> None:
    ev = {"tipo": "feedback", "origine": origine, "testo": testo}
    if termine:
        glossary = m.carica_glossario(_dir(dati_dir) / "glossario.json")
        glossary[termine.lower()] = semplice or ""
        d = _dir(dati_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "glossario.json").write_text(json.dumps(dict(sorted(glossary.items())), ensure_ascii=False, indent=2) + "\n",
                                          encoding="utf-8", newline="\n")
        ev.update(termine=termine.lower(), semplice=semplice or "")
    _append(dati_dir, ev)


def _kind(problem: str) -> str:
    if problem.startswith("gergo statistico"):
        return "gergo statistico"
    for key in ("Gulpease", "frase di", "troppi numeri", "troppe parentesi", "testo lungo"):
        if key in problem:
            return {"Gulpease": "indice Gulpease basso", "frase di": "frase troppo lunga"}.get(key, key)
    return problem


def aggiorna_documento(dati_dir=None, out: Path | None = None) -> Path:
    ev = eventi(dati_dir)
    glossary = m.carica_glossario(_dir(dati_dir) / "glossario.json")
    testi = [e for e in ev if e["tipo"] in ("testo", "riscrittura")]
    kinds = collections.Counter(_kind(p) for e in testi for p in e["problemi_prima"])
    jargon = collections.Counter(p.split(": ", 1)[1] for e in testi for p in e["problemi_prima"]
                                 if p.startswith("gergo statistico"))
    azioni = collections.Counter(a.split(" dopo ")[0].split(":")[0] for e in testi for a in e["azioni"])
    bad = [e for e in testi if e["problemi_prima"]]
    lines = [
        "# Leggibilità dei testi: regole e lezioni apprese", "",
        "File generato da `python -m nlp.leggibilita documento`: non modificarlo a mano. Le regole stanno in "
        "`nlp/leggibilita/regole.md`, il glossario in `nlp/leggibilita/dati/glossario.json`, gli eventi in "
        "`nlp/leggibilita/dati/eventi.jsonl`.", "",
        "## Come si misura",
        f"- Indice Gulpease (per l'italiano, 0-100): almeno {m.MIN_GULPEASE:.0f} (sopra 80 facile, 60-80 licenza media, "
        "sotto 40 difficile).",
        f"- Frasi di al massimo {m.MAX_SENTENCE_WORDS} parole, al massimo {m.MAX_NUMBERS} numeri e "
        f"{m.MAX_PARENTHESES} parentesi per testo, al massimo {m.MAX_WORDS} parole, niente gergo del glossario.",
        "- Il controllo misura la forma, non l'utilità: dopo averlo superato il testo va comunque riletto da una persona.", "",
        "## Come si usa",
        "```",
        'python -m nlp.leggibilita check --file testo.txt        # misura, esce con 1 se non passa',
        'python -m nlp.leggibilita migliora --file testo.txt     # correzioni meccaniche e cosa riscrivere a mano',
        'python -m nlp.leggibilita riscritto --prima a.txt --dopo b.txt   # registra una riscrittura riuscita',
        'python -m nlp.leggibilita feedback "non capisco X" --termine X --semplice Y',
        "python -m nlp.leggibilita documento                    # rigenera questo file",
        "```",
        "Ciclo: scrivere, misurare, correggere o riscrivere, rimisurare, finché non passa; registrare la riscrittura "
        "e ogni feedback ricevuto.", "",
        "## Regole di scrittura", REGOLE_PATH.read_text(encoding="utf-8").strip(), "",
        "## Problemi più frequenti",
        f"Testi controllati: {len(testi)}; non passavano al primo colpo: {len(bad)}.",
    ]
    if testi:
        lines.append(f"Punteggio medio Gulpease: {sum(e['gulpease_prima'] for e in testi) / len(testi):.1f} prima, "
                     f"{sum(e['gulpease_dopo'] for e in testi) / len(testi):.1f} dopo.")
    lines += ["", "| Problema | Volte |", "|---|---|"]
    lines += [f"| {k} | {n} |" for k, n in kinds.most_common()] or ["| nessuno | 0 |"]
    if jargon:
        lines += ["", "Termini di gergo più frequenti: " + ", ".join(f"{k} ({n})" for k, n in jargon.most_common(8)) + "."]
    if azioni:
        lines += ["", "Correzioni meccaniche più usate: " + ", ".join(f"{k} ({n})" for k, n in azioni.most_common(5)) + "."]
    lines += ["", "## Esempi prima e dopo"]
    examples = [e for e in testi if e["dopo"] and e["gulpease_dopo"] >= e["gulpease_prima"] and e["problemi_prima"]]
    examples = sorted(examples, key=lambda e: e["gulpease_dopo"] - e["gulpease_prima"], reverse=True)[:5]
    for e in examples:
        lines += ["", f"- Prima (Gulpease {e['gulpease_prima']:.0f}): {e['prima'][:400]}",
                  f"  Dopo (Gulpease {e['gulpease_dopo']:.0f}): {e['dopo'][:400]}"]
    if not examples:
        lines.append("Ancora nessun esempio.")
    fb = [e for e in ev if e["tipo"] == "feedback"]
    lines += ["", "## Feedback ricevuti"]
    for e in fb:
        extra = f" → termine '{e['termine']}': {e['semplice'] or 'da togliere'}" if e.get("termine") else ""
        lines.append(f"- {e['ts'][:10]} ({e['origine']}): {e['testo']}{extra}")
    if not fb:
        lines.append("Nessuno.")
    lines += ["", "## Glossario (gergo e alternativa semplice)", "", "| Gergo | Meglio |", "|---|---|"]
    lines += [f"| {k} | {v or 'togliere'} |" for k, v in sorted(glossary.items())]
    path = Path(out) if out else DOC_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path
