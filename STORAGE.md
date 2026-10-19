# Storage layer: Postgres (Docker) + Alembic

Infrastruttura di storage del data pipeline per taxidrivers.it. Un unico container
Postgres, versionato via Alembic con migration scritte in **SQL puro** (nessun ORM).

## Struttura

```
taxi_drivers_lab/
├── docker-compose.yml              # solo Postgres
├── .env.example                    # template credenziali/porta (copia in .env)
├── requirements.txt                # alembic + psycopg2 + python-dotenv
├── alembic.ini                     # config Alembic
├── alembic/
│   ├── env.py                      # costruisce la connection string da .env
│   ├── script.py.mako              # template per future migration
│   └── versions/
│       └── 0001_articles_star_schema.py   # schema iniziale (upgrade/downgrade)
```

## Setup una tantum

1. **Creare il file `.env`** a partire dal template:

   ```powershell
   Copy-Item .env.example .env
   ```

   Modifica `POSTGRES_PASSWORD` (e le altre variabili se serve). Il file `.env`
   è escluso dal versionamento (vedi `.gitignore`).

2. **Creare il virtualenv Python e installare le dipendenze** (dal repo root):

   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. **Avviare il container Postgres**:

   ```powershell
   docker compose up -d
   ```

   Postgres resta in ascolto su `localhost:${POSTGRES_PORT}` (default `5434`).
   Verifica che sia pronto:

   ```powershell
   docker compose ps
   ```

## Eseguire le migration

La connection string di Alembic viene costruita automaticamente in `alembic/env.py`
a partire da `.env` (stesso file usato da docker-compose). Non serve configurare
nulla a mano: basta lanciare il comando dal repo root con il venv attivo.

Prima esecuzione (crea tutte le tabelle):

```powershell
alembic upgrade head
```

Verifica lo stato:

```powershell
alembic current        # -> 0001_articles_star_schema
alembic history        # elenco revisioni
```

Rollback dell'ultima migration (droppa tutte le tabelle):

```powershell
alembic downgrade base
```

## Comandi utili

| Comando | Effetto |
|---|---|
| `docker compose up -d` | avvia Postgres in background |
| `docker compose down` | ferma il container (il volume persiste) |
| `docker compose down -v` | ferma **e** cancella i dati |
| `alembic upgrade head` | applica tutte le migration |
| `alembic downgrade base` | torna allo schema vuoto |
| `alembic revision -m "descrizione"` | crea una nuova migration vuota |

## Connessione manuale al DB (debug)

```powershell
docker compose exec postgres psql -U $env:POSTGRES_USER -d $env:POSTGRES_DB
```

## Note sui vincoli

- **Niente ORM**: `target_metadata` in `env.py` è `None` e le migration usano solo
  `op.execute()` con SQL puro. Non esiste alcun layer SQLAlchemy dichiarativo.
- **Nessuna estensione Postgres** (pgcrypto/uuid-ossp): la DDL non le richiede.
- La DDL di `fact_ga4_daily`, `fact_gsc_daily` e `article_features` **non** è inclusa
  in questo schema: aggiungerla come migration separata richiede prima la loro
  struttura ufficiale.
