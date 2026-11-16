"""
midreport_render.py

Legge dati.json (prodotto da midreport_run.py) e la redazione (JSON con sintesi,
chart_sentence, contesto_note opzionale) e scrive midreport_settimanaNN.html.

Uso (dalla cartella ga4_client):
    python midreport_render.py --dir <cartella> --redazione <redazione.json>
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import midreport_report as rep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, required=True, help="cartella con dati.json")
    parser.add_argument("--redazione", type=Path, required=True, help="JSON con sintesi, chart_sentence, contesto_note")
    args = parser.parse_args(argv)

    data = json.loads((args.dir / "dati.json").read_text(encoding="utf-8"))
    red = json.loads(args.redazione.read_text(encoding="utf-8"))
    start = dt.date.fromisoformat(data["start"])
    end = dt.date.fromisoformat(data["end"])

    html = rep.render_html(start, end, red["sintesi"], data["sections"], data["notes"],
                           red["chart_sentence"], red.get("contesto_note"))
    out = args.dir / f"midreport_settimana{start.isocalendar()[1]:02d}.html"
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)
        f.write("\n")
    print(f"[midreport] html: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
