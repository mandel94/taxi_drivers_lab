"""
ciclo.py

Ciclo di miglioramento di un testo: misura, corregge quello che si puo' correggere senza cambiare
il senso (frasi lunghe spezzate a ";" o a una congiunzione, parentesi in eccesso trasformate in
virgole), rimisura, e dice con precisione cosa resta da riscrivere a mano (gergo con la
parola semplice suggerita, troppi numeri, frasi senza punti di taglio). Non riscrive mai il gergo
da solo: l'accordo di genere e articoli lo sistema chi scrive.
"""

from __future__ import annotations

import re

from nlp.leggibilita import misura as m

_CONJ = re.compile(r",\s+(ma|però|mentre|quindi)\s+", re.IGNORECASE)


def _cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _split_long(text: str) -> tuple[str, list[str]]:
    """Spezza le frasi oltre il limite a ';' o prima di ma/però/mentre/quindi."""
    actions = []
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = []
    for sent in parts:
        if len(m._words(sent)) > m.MAX_SENTENCE_WORDS:
            if "; " in sent:
                head, tail = sent.split("; ", 1)
                sent = f"{head}. {_cap(tail)}"
                actions.append(f"frase spezzata al punto e virgola dopo '{head[-20:]}'")
            else:
                hit = _CONJ.search(sent)
                if hit:
                    head, tail = sent[:hit.start()], sent[hit.end():]
                    sent = f"{head}. {_cap(hit.group(1))} {tail}"
                    actions.append(f"frase spezzata prima di '{hit.group(1)}'")
        out.append(sent)
    return " ".join(out), actions


def _drop_extra_parentheses(text: str) -> tuple[str, list[str]]:
    actions, seen = [], 0

    def repl(match: re.Match) -> str:
        nonlocal seen
        seen += 1
        if seen <= m.MAX_PARENTHESES:
            return match.group(0)
        actions.append(f"parentesi trasformata in virgole: '{match.group(1)[:25]}'")
        return f", {match.group(1)},"

    out = re.sub(r"\(([^()]*)\)", repl, text)
    out = re.sub(r",\s*,", ",", out)
    out = re.sub(r",\s*([.!?])", r"\1", out)
    return re.sub(r"\s+,", ",", out), actions


def _da_riscrivere(text: str, result: dict, glossario: dict[str, str]) -> list[str]:
    todo = []
    for p in result["problems"]:
        if p.startswith("gergo statistico: "):
            term = p.split(": ", 1)[1]
            todo.append(f"sostituire '{term}' con '{glossario[term]}'" if term in glossario
                        else f"togliere '{term}'")
        else:
            todo.append(p)
    return todo


def migliora(text: str, glossario: dict[str, str] | None = None, max_iter: int = 5) -> dict:
    """{testo, ok, iterazioni: [{gulpease, problemi, azioni}], da_riscrivere}."""
    glossario = m.carica_glossario() if glossario is None else glossario
    cur, steps = text, []
    for _ in range(max_iter):
        res = m.check(cur, glossario)
        actions = []
        if res["problems"]:
            new, a1 = _split_long(cur)
            new, a2 = _drop_extra_parentheses(new)
            actions = a1 + a2
        steps.append({"gulpease": res["gulpease"], "problemi": res["problems"], "azioni": actions})
        if not res["problems"] or not actions:
            break
        cur = new
    final = m.check(cur, glossario)
    return {"testo": cur, "ok": final["ok"], "iterazioni": steps,
            "da_riscrivere": [] if final["ok"] else _da_riscrivere(cur, final, glossario)}
