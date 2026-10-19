"""
fetch_taxidrivers_ga4.py

Esempio di utilizzo di GA4Client per popolare fact_ga4_daily con i
dati della proprieta' GA4 di taxidrivers.it.

Setup una tantum: vedi PROMPT_ga4client.md per come scaricare
client_secrets.json da Google Cloud Console e metterlo in questa
cartella.

Uso:
    export GA4_PROPERTY_ID=123456789   # property ID GA4, non measurement ID (G-XXXX)
    python fetch_taxidrivers_ga4.py --start 7daysAgo --end yesterday

Al primo avvio si apre il browser per il consenso OAuth2. Le
esecuzioni successive riusano token.json senza intervento manuale.
"""

import argparse
import os

from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())  # carica variabili da .env in os.environ

from ga4_client import GA4Client


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="7daysAgo")
    parser.add_argument("--end", default="yesterday")
    parser.add_argument("--out", default="fact_ga4_daily_staging.csv")
    args = parser.parse_args()

    property_id = os.environ["GA4_PROPERTY_ID"]

    client = GA4Client(
        client_secrets_path="client_secrets.json",
        token_path="token.json",
    )

    df = client.run_report(property_id=property_id, start_date=args.start, end_date=args.end)
    print(f"{len(df)} righe recuperate ({args.start} -> {args.end})")
    print(df.head())

    df.to_csv(args.out, index=False)
    print(f"Salvato in {args.out}, pronto per l'insert in fact_ga4_daily")


if __name__ == "__main__":
    main()