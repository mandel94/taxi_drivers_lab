"""
midreport_archive.py

Archivia i Midreport nella KB degli insight (sottocartella "midreports").

Uso (dalla cartella ga4_client):
    python midreport_archive.py save --dir C:\\percorso\\cartella_settimana [--kb C:\\percorso\\Insight KB]
        [--drive-folder-id X] [--gmail-draft-id Y]
    python midreport_archive.py backfill --corpus C:\\percorso\\corpus [--kb C:\\percorso\\Insight KB]

save: legge dati.json e redazione.json dalla cartella della settimana.
backfill: legge i *.txt del corpus (righe SUBJECT:/DATE:/TO:/ATTACHMENTS:, riga vuota, corpo).
Default di --kb: variabile TD_INSIGHT_KB, altrimenti la cartella Insight KB di taxi_drivers.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

import midreport_storico as sto

DEFAULT_KB = r"C:\Users\manuel.deluzi\OneDrive - Havas\Projects\personali\taxi_drivers\reports\weekly\Insight KB"


def kb_folder(kb) -> Path:
    return Path(kb or os.environ.get("TD_INSIGHT_KB") or DEFAULT_KB) / "midreports"


def cmd_save(args) -> int:
    d = args.dir
    data = json.loads((d / "dati.json").read_text(encoding="utf-8"))
    red = json.loads((d / "redazione.json").read_text(encoding="utf-8"))
    record = sto.build_record(
        dt.date.fromisoformat(data["start"]), dt.date.fromisoformat(data["end"]),
        data["subject"], red["sintesi"], data["sections"], data["notes"],
        insights=red.get("insights"), chart_sentence=red["chart_sentence"],
        reliability_warning=data["reliability_warning"], category_stats=data["category_stats"],
        n_articles=data["n_articles"], drive_folder_id=args.drive_folder_id,
        gmail_draft_id=args.gmail_draft_id)
    path = sto.upsert_week(kb_folder(args.kb), record)
    print(f"[archive] {record['week_id']} salvata in {path}")
    return 0


def _parse_corpus_file(path: Path):
    head, _, body = path.read_text(encoding="utf-8").replace("\r\n", "\n").partition("\n\n")
    fields = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        fields[key.strip().upper()] = value.strip()
    date = dt.datetime.fromisoformat(fields["DATE"].replace("Z", "+00:00")).date()
    return body, date, fields.get("SUBJECT", "")


def cmd_backfill(args) -> int:
    folder = kb_folder(args.kb)
    for path in sorted(args.corpus.glob("*.txt")):
        body, date, subject = _parse_corpus_file(path)
        record = sto.parse_sent_report(body, date)
        if subject:
            record["subject"] = subject
        sto.upsert_week(folder, record)
        print(f"{path.name}: {record['week_id']} {record['metric']} "
              f"categorie={len(record['sections'])} sintesi={len(record['sintesi'])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    save = sub.add_parser("save", help="archivia la settimana da dati.json e redazione.json")
    save.add_argument("--dir", type=Path, required=True, help="cartella della settimana")
    save.add_argument("--kb", type=Path, help="cartella Insight KB")
    save.add_argument("--drive-folder-id")
    save.add_argument("--gmail-draft-id")
    save.set_defaults(func=cmd_save)

    back = sub.add_parser("backfill", help="archivia i report inviati da un corpus di .txt")
    back.add_argument("--corpus", type=Path, required=True, help="cartella con i *.txt")
    back.add_argument("--kb", type=Path, help="cartella Insight KB")
    back.set_defaults(func=cmd_backfill)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
