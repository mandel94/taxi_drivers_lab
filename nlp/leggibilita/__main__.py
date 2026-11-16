"""
Uso (dalla radice del repo):
    python -m nlp.leggibilita check [--file F | "testo"]            misura; esce con 1 se non passa
    python -m nlp.leggibilita migliora [--file F | "testo"] [--origine X]
                                                                    correzioni meccaniche e cosa riscrivere
    python -m nlp.leggibilita riscritto --prima F --dopo F          registra una riscrittura riuscita
    python -m nlp.leggibilita feedback "testo" [--termine T --semplice S]
    python -m nlp.leggibilita documento [--out F]                   rigenera docs/leggibilita.md
Il testo puo' arrivare anche da stdin.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nlp.leggibilita import lezioni
from nlp.leggibilita import misura as m


def _text(args) -> str:
    if getattr(args, "file", None):
        return Path(args.file).read_text(encoding="utf-8")
    if getattr(args, "testo", None):
        return args.testo
    return sys.stdin.read()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="nlp.leggibilita", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("check", "migliora"):
        p = sub.add_parser(name)
        p.add_argument("testo", nargs="?")
        p.add_argument("--file")
        if name == "check":
            p.add_argument("--max-parole", type=int, default=m.MAX_WORDS,
                           help="limite di parole (default 90: per documenti lunghi alzarlo)")
        if name == "migliora":
            p.add_argument("--origine", default="altro")
    p = sub.add_parser("riscritto")
    p.add_argument("--prima", required=True)
    p.add_argument("--dopo", required=True)
    p.add_argument("--origine", default="altro")
    p = sub.add_parser("feedback")
    p.add_argument("testo")
    p.add_argument("--termine")
    p.add_argument("--semplice")
    p = sub.add_parser("documento")
    p.add_argument("--out")
    args = parser.parse_args(argv)

    if args.cmd == "check":
        r = m.check(_text(args), max_words=args.max_parole)
        print(f"Gulpease {r['gulpease']:.0f} | {r['words']} parole | frase più lunga {r['longest_sentence']} | "
              f"{r['numbers']} numeri")
        for pr in r["problems"]:
            print(f"- {pr}")
        print("OK" if r["ok"] else "NON PASSA")
        return 0 if r["ok"] else 1
    if args.cmd == "migliora":
        res = lezioni.garantisci(_text(args), origine=args.origine)
        for i, it in enumerate(res["iterazioni"], 1):
            print(f"giro {i}: Gulpease {it['gulpease']:.0f}, problemi {len(it['problemi'])}, azioni {len(it['azioni'])}")
        print("\n" + res["testo"] + "\n")
        for d in res["da_riscrivere"]:
            print(f"- da riscrivere: {d}")
        print("OK" if res["ok"] else "NON PASSA: riscrivere e rilanciare")
        return 0 if res["ok"] else 1
    if args.cmd == "riscritto":
        ev = lezioni.registra_riscrittura(Path(args.prima).read_text(encoding="utf-8"),
                                          Path(args.dopo).read_text(encoding="utf-8"), origine=args.origine)
        print(f"Gulpease {ev['gulpease_prima']:.0f} → {ev['gulpease_dopo']:.0f}; {'OK' if ev['ok'] else 'NON PASSA ancora'}")
        return 0
    if args.cmd == "feedback":
        lezioni.feedback(args.testo, termine=args.termine, semplice=args.semplice)
        print("Feedback registrato" + (f"; '{args.termine}' aggiunto al glossario" if args.termine else ""))
        return 0
    print(lezioni.aggiorna_documento(out=Path(args.out) if args.out else None))
    return 0


if __name__ == "__main__":
    sys.exit(main())
