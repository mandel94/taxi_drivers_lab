"""
misura.py

Misura di leggibilita' dei testi, pensata per chi legge senza essere un analista.
  - indice Gulpease (formula per l'italiano, 0-100): 89 + (300 * frasi - 10 * lettere) / parole.
    Sopra 80 facile, 60-80 licenza media, 40-60 superiori, sotto 40 difficile;
  - regole semplici: frasi corte, pochi numeri, poche parentesi, niente gergo (glossario).
Un testo e' "ok" se supera tutti i controlli. Nessuna rete.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

MIN_GULPEASE = 60.0
MAX_SENTENCE_WORDS = 25
MAX_NUMBERS = 6
MAX_PARENTHESES = 1
MAX_WORDS = 90

PACKAGE_DATI = Path(__file__).resolve().parent / "dati"
_NUMBER = r"\d+(?:[.,]\d+)*%?"
_TOKEN = re.compile(rf"{_NUMBER}|[^\W\d_]+(?:['’][^\W\d_]+)*")
_Z = re.compile(r"\bz\s*=", re.IGNORECASE)


def dati_dir() -> Path:
    """Cartella di glossario ed eventi: TD_LEGGIBILITA_DATI se impostata, altrimenti quella del pacchetto."""
    env = os.environ.get("TD_LEGGIBILITA_DATI")
    return Path(env) if env else PACKAGE_DATI


def carica_glossario(path: Path | None = None) -> dict[str, str]:
    """{termine di gergo: alternativa semplice}. Se il file non c'e', quello di partenza del pacchetto."""
    candidates = [Path(path)] if path else [dati_dir() / "glossario.json"]
    candidates.append(PACKAGE_DATI / "glossario.json")
    for p in candidates:
        if p.exists():
            return {k.lower(): v for k, v in json.loads(p.read_text(encoding="utf-8")).items()}
    return {}


def pulisci(text: str) -> str:
    """Toglie markdown, codice e indirizzi; ogni riga diventa una frase."""
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:#+\s*|[-*•]\s+|\d+[.)]\s+)", "", line)
        line = re.sub(r"[*_]{1,3}", "", line).strip()
        if not line:
            continue
        lines.append(line if re.search(r"[.!?:]$", line) else line + ".")
    return " ".join(lines)


def _clean(text: str) -> str:
    return re.sub(r"(?<=\d)\.(?=\d)", "", pulisci(text))  # 2.334 non chiude una frase


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"[.!?]+(?:\s+|$)", _clean(text)) if re.search(r"\w", s)]


def _words(text: str) -> list[str]:
    return _TOKEN.findall(_clean(text))


def gulpease(text: str) -> float:
    words = _words(text)
    if not words:
        return 100.0
    letters = sum(1 for w in words for ch in w if ch.isalpha())
    value = 89 + (300 * len(_sentences(text)) - 10 * letters) / len(words)
    return round(max(0.0, min(100.0, value)), 1)


def jargon_found(text: str, glossario: dict[str, str] | None = None) -> list[str]:
    glossario = carica_glossario() if glossario is None else glossario
    found = set()
    if glossario:
        pattern = r"\b(?:" + "|".join(re.escape(k) for k in sorted(glossario, key=len, reverse=True)) + r")\b"
        found |= {m.group(0).lower() for m in re.finditer(pattern, text, flags=re.IGNORECASE)}
    if _Z.search(text):
        found.add("z =")
    return sorted(found)


def check(text: str, glossario: dict[str, str] | None = None, max_words: int = MAX_WORDS) -> dict:
    sentences = _sentences(text)
    words = _words(text)
    numbers = [w for w in words if re.fullmatch(_NUMBER, w)]
    longest = max((len(_words(s)) for s in sentences), default=0)
    score = gulpease(text)
    clean = _clean(text)
    problems = []
    if score < MIN_GULPEASE:
        problems.append(f"indice Gulpease {score:.0f}, sotto {MIN_GULPEASE:.0f}: parole e frasi troppo lunghe")
    if longest > MAX_SENTENCE_WORDS:
        problems.append(f"una frase di {longest} parole (massimo {MAX_SENTENCE_WORDS}): spezzarla")
    if len(numbers) > MAX_NUMBERS:
        problems.append(f"troppi numeri ({len(numbers)}, massimo {MAX_NUMBERS}): tenere i più importanti")
    if clean.count("(") > MAX_PARENTHESES:
        problems.append(f"troppe parentesi ({clean.count('(')}, massimo {MAX_PARENTHESES})")
    if len(words) > max_words:
        problems.append(f"testo lungo ({len(words)} parole, massimo {max_words})")
    for term in jargon_found(clean, glossario):
        problems.append(f"gergo statistico: {term}")
    return {"gulpease": score, "words": len(words), "sentences": len(sentences), "longest_sentence": longest,
            "numbers": len(numbers), "problems": problems, "ok": not problems}


def check_sintesi(items: list[str], glossario: dict[str, str] | None = None) -> list[tuple[int, list[str]]]:
    """Per ogni testo che non passa: (posizione, problemi)."""
    out = []
    for i, t in enumerate(items):
        r = check(t, glossario)
        if not r["ok"]:
            out.append((i, r["problems"]))
    return out
