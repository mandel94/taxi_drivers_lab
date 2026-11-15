"""
build_prompt.py

Compone il prompt per generare i titoli delle sezioni, l'intro, "Prima di
lasciarci" e "Uno sguardo d'insieme" di un Trend Radar:

1. istruzioni e formato d'uscita;
2. il profilo qualitativo (profilo_stile.md);
3. esempi reali: le cornici degli ultimi articoli di addestramento, con i
   titoletti delle sezioni, cosi' il modello vede come l'intro rispecchia
   l'ordine delle sezioni (le descrizioni da sole portano alla caricatura,
   gli esempi tengono il registro);
4. coppie "apertura della sezione -> titolo" dei numeri recenti, per i titoli;
5. il materiale della settimana.

Uso (dalla root del progetto):
    # materiale scritto da te (vedi README per il formato)
    .venv\\Scripts\\python.exe -m nlp.style_profile.build_prompt --materiale appunti.md

    # giro di prova: materiale ricavato da un articolo hold-out
    .venv\\Scripts\\python.exe -m nlp.style_profile.build_prompt --da-holdout 565041

Con --da-holdout scrive anche giri/<id>_originale.md (la cornice vera, per
il confronto), giri/<id>_titoli_originali.md (i titoli veri) e
giri/<id>_materiale.md. Nel materiale le sezioni non hanno il titolo
(### Sezione 1, ...): i titoli li genera il modello. Con --con-titoli il
materiale riporta i titoli veri.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from nlp.style_profile import config

FRAME_TYPES = ("intro", "prima_di_lasciarci", "sguardo")

ISTRUZIONI = """Sei la redazione di TaxiDrivers e scrivi le parti di cornice del Trend Radar della settimana: i titoli delle sezioni, l'intro, l'elenco "Prima di lasciarci" e il paragrafo "Uno sguardo d'insieme".

Segui il profilo di stile qui sotto. Gli esempi sono articoli reali dell'autore: imita il loro registro, il ritmo e la struttura, ma non copiarne le frasi (tranne la formula d'apertura dell'intro, che è fissa). Usa solo i fatti del materiale della settimana: non inventare titoli, date, premi o link.

Il materiale contiene le sezioni del corpo, in ordine. Per ogni sezione scrivi un titolo; se il materiale ne riporta già uno, trattalo come una nota di lavoro e proponi il tuo. L'intro riprende le sezioni nello stesso ordine dei titoli.

Due punti su cui si sbaglia più spesso:
- I titoli hanno al massimo 9 parole e non riassumono la trama: con un'opera come soggetto il verbo è "è", altrimenti si scrive "*Opera*, lettura".
- Ogni voce di "Prima di lasciarci" aggiunge qualcosa all'URL che linka (un giudizio, un'informazione, una battuta) e non ne ricopia le parole; il titolo dell'opera, in corsivo, sta dentro il link. Se il materiale riporta una nota per l'URL, usala.

Restituisci solo il testo, in Markdown, con questa struttura esatta:

## Titoli delle sezioni
1. <titolo della sezione 1, con i titoli delle opere in *corsivo*>
2. ...

## Intro
<due paragrafi>

## Prima di lasciarci
- <voce con [link](url)>
...

## Uno sguardo d'insieme
<un paragrafo>"""


def load_rows() -> list[dict]:
    return [json.loads(l) for l in open(config.CORPUS_JSONL, encoding="utf-8")]


def articles(rows: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = {}
    for r in sorted(rows, key=lambda r: (r["published"], r["article_id"], r["section_index"])):
        out.setdefault(r["article_id"], []).append(r)
    return out


def frame_example(sections: list[dict]) -> str:
    """Cornice di un articolo reale, con i titoletti del corpo al loro posto."""
    head = sections[0]
    out = [f"### Esempio: {head['title']} (pubblicato il {head['published']})", ""]
    for s in sections:
        if s["section_type"] == "intro":
            out += ["## Intro", s["text_md"], ""]
        elif s["section_type"] in ("corpo", "spunti"):
            out += [f"## {s.get('heading_md') or s['heading']}", "[sezione del corpo, omessa]", ""]
        elif s["section_type"] == "prima_di_lasciarci":
            out += ["## Prima di lasciarci", s["text_md"], ""]
        elif s["section_type"] == "sguardo":
            out += ["## Uno sguardo d'insieme", s["text_md"], ""]
    return "\n".join(out)


def pick_examples(rows: list[dict], n: int) -> list[list[dict]]:
    """Gli N articoli di addestramento piu' recenti, preferendo quelli con
    "Prima di lasciarci" (il formato in uso)."""
    arts = [a for a in articles(rows).values() if a[0]["split"] == "train"]
    with_pdl = [a for a in arts if any(s["section_type"] == "prima_di_lasciarci" for s in a)]
    pool = with_pdl if len(with_pdl) >= n else arts
    return pool[-n:]


_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")

TITLE_PAIR_WORDS = 40


def title_pairs(rows: list[dict]) -> str:
    """Coppie "apertura della sezione -> titolo" dei numeri di addestramento
    recenti (dal formato attuale dei titoli): esempi per generare i titoli."""
    out = ["Per ogni sezione: l'apertura del testo e il titolo che l'autore le ha dato.", ""]
    for r in sorted(rows, key=lambda r: (r["published"], r["article_id"], r["section_index"])):
        if r["split"] != "train" or r["section_type"] != "corpo" or not r.get("heading"):
            continue
        if r["published"] < config.TITLES_RECENT_FROM:
            continue
        words = (r["paragraphs"][0] if r["paragraphs"] else r["text_plain"]).split()
        opening = " ".join(words[:TITLE_PAIR_WORDS]) + (" [...]" if len(words) > TITLE_PAIR_WORDS else "")
        out += [f"- Apertura: «{opening}»", f"  Titolo: {r.get('heading_md') or r['heading']}"]
    return "\n".join(out)


def materiale_da_holdout(article_id: int, rows: list[dict], con_titoli: bool = False) -> tuple[str, str, str]:
    """Materiale per il giro di prova, cornice originale e titoli originali.

    Il materiale contiene cio' che l'autore aveva davanti: le date, le sezioni
    del corpo per intero e i link dell'elenco finale (senza le sue frasi).
    Senza `con_titoli` le sezioni sono "Sezione 1, 2, ...": i titoli li deve
    generare il modello, e quelli veri restano per il confronto.
    """
    secs = articles(rows)[article_id]
    title = secs[0]["title"]
    m = re.search(r"\(([^)]+)\)\s*$", title)
    settimana = m.group(1) if m else "date non indicate nel titolo"
    mat = [f"# Materiale della settimana ({settimana})", "", f"Titolo dell'articolo: {title}", "",
           "## Sezioni del corpo, in ordine", ""]
    n = 0
    titoli_orig = []
    for s in secs:
        if s["section_type"] in ("corpo", "spunti"):
            n += 1
            label = (s.get("heading_md") or s["heading"]) if con_titoli else f"Sezione {n}"
            mat += [f"### {label}", "", s["text_md"], ""]
            if s["section_type"] == "corpo":
                titoli_orig.append(s.get("heading_md") or s["heading"])
    pdl = [s for s in secs if s["section_type"] == "prima_di_lasciarci"]
    if pdl:
        mat += ["## Articoli da rilanciare in \"Prima di lasciarci\"", ""]
        for line in pdl[0]["text_md"].splitlines():
            for _, url in _LINK.findall(line):
                mat.append(f"- {url}")
        mat.append("")
    orig = [f"# {title} (cornice originale)", ""]
    for s in secs:
        if s["section_type"] == "intro":
            orig += ["## Intro", "", s["text_md"], ""]
        elif s["section_type"] == "prima_di_lasciarci":
            orig += ["## Prima di lasciarci", "", s["text_md"], ""]
        elif s["section_type"] == "sguardo":
            orig += ["## Uno sguardo d'insieme", "", s["text_md"], ""]
    return "\n".join(mat), "\n".join(orig), "\n".join(titoli_orig) + "\n"


def build_prompt(materiale: str, n_esempi: int = 3, rows: list[dict] | None = None) -> str:
    rows = rows if rows is not None else load_rows()
    profilo = config.PROFILE_MD.read_text(encoding="utf-8")
    esempi = "\n\n".join(frame_example(a) for a in pick_examples(rows, n_esempi))
    return "\n\n".join([
        ISTRUZIONI,
        "# PROFILO DI STILE\n\n" + profilo,
        "# ESEMPI REALI\n\n" + esempi,
        "# ESEMPI DI TITOLI DELLE SEZIONI\n\n" + title_pairs(rows),
        "# MATERIALE DELLA SETTIMANA\n\n" + materiale,
    ])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--materiale", help="file Markdown con il materiale della settimana")
    src.add_argument("--da-holdout", type=int, help="article_id di un articolo hold-out")
    ap.add_argument("--esempi", type=int, default=3, help="quanti articoli reali usare come esempio")
    ap.add_argument("--con-titoli", action="store_true",
                    help="con --da-holdout: il materiale riporta i titoli veri delle sezioni")
    ap.add_argument("--out", help="dove salvare il prompt (default: giri/prompt_<nome>.md)")
    args = ap.parse_args()

    rows = load_rows()
    config.CHECKS_DIR.mkdir(parents=True, exist_ok=True)
    if args.da_holdout:
        if args.da_holdout not in config.HOLDOUT_IDS:
            raise SystemExit(f"{args.da_holdout} non e' tra gli hold-out {sorted(config.HOLDOUT_IDS)}: "
                             "usarlo come prova sarebbe un confronto con un testo gia' visto dal profilo.")
        materiale, originale, titoli = materiale_da_holdout(args.da_holdout, rows, args.con_titoli)
        (config.CHECKS_DIR / f"{args.da_holdout}_materiale.md").write_text(materiale, encoding="utf-8")
        (config.CHECKS_DIR / f"{args.da_holdout}_originale.md").write_text(originale, encoding="utf-8")
        (config.CHECKS_DIR / f"{args.da_holdout}_titoli_originali.md").write_text(titoli, encoding="utf-8")
        name = str(args.da_holdout)
    else:
        path = Path(args.materiale)
        materiale = path.read_text(encoding="utf-8-sig")
        name = path.stem

    prompt = build_prompt(materiale, args.esempi, rows)
    out = Path(args.out) if args.out else config.CHECKS_DIR / f"prompt_{name}.md"
    out.write_text(prompt, encoding="utf-8")
    print(f"prompt: {len(prompt.split())} parole -> {out}")


if __name__ == "__main__":
    main()
