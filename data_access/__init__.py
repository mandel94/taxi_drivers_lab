"""Data-access layer del progetto: connessione e query riusabili verso
il PostgreSQL del warehouse (schema a stella taxidrivers).

Moduli:
  - db.py:      costruzione DSN, connessione psycopg2, query -> DataFrame.
  - metrics.py: estrazione degli articoli con performance giornaliera GA4.
"""
