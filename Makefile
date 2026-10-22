# =====================================================================
# Makefile di progetto: orchestrazione init DB (Docker + Alembic),
# ingestion articoli da WP REST API (Node.js) e metriche da GA4 Data API,
# oltre al layer di data discovery/dashboard Metabase.
#
# Struttura attesa:
#   ./docker-compose.yml
#   ./requirements.txt      (alembic, psycopg2-binary, ecc.)
#   ./.env                  (credenziali Postgres, vedi .env.example)
#   ./alembic/               (env.py, versions/)
#   ./alembic.ini           (nella root del progetto)
#   ./wp_client/              (package.json, ingest-articles.js, ...)
#   ./ga4_client/              (ga4_client.py, ingest_ga4.py, client_secrets.json)
#   ./scripts/                (query SQL di verifica/diagnostica, non versionamento schema)
# =====================================================================

# Carica le variabili da .env se presente, cosi POSTGRES_USER/DB/PORT
# sono disponibili sia per i target Make sia per i comandi psql/alembic.
ifneq (,$(wildcard .env))
	include .env
	export
endif

POSTGRES_USER ?= postgres
POSTGRES_DB ?= taxidrivers
POSTGRES_PORT ?= 5432
DATABASE_URL ?= postgresql://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@localhost:$(POSTGRES_PORT)/$(POSTGRES_DB)

# Immagine tbls e cartella di output della documentazione del DB.
TBLS_IMAGE ?= ghcr.io/k1low/tbls:latest
DOCS_DIR ?= docs/db

# Porta locale su cui e' esposto Metabase (data discovery/dashboard sul warehouse).
METABASE_PORT ?= 3000

# Limite massimo di pagine da scaricare durante l'ingestion degli articoli
MAX_PAGES ?= 0

# Numero di giorni da ingerire in modalita' giornaliera (default: ultimo mese).
GA4_DAYS ?= 30

# Argomenti passati a ingest_ga4.py. Default: ultimi GA4_DAYS giorni.
# Per un range esplicito: make ingest-ga4 GA4_ARGS="--start 2026-08-01 --end 2026-08-15"
GA4_ARGS ?= --days $(GA4_DAYS)

# Argomenti passati a ingest_ga4_site.py (totali di sito, canali, utenti su periodo).
# Default: ultimi 3 giorni (GA4 rivede i dati recenti). Backfill:
# make ingest-ga4-site GA4_SITE_ARGS="--start 2025-08-01 --end yesterday"
GA4_SITE_ARGS ?= --days 3

# Primo giorno atteso per le due coperture GA4: unica fonte di verita'. Le usano il backfill
# dinamico dell'ETL (--floor) e dbt (--vars), cosi' non si disallineano. Prima di queste date
# nessuno cerca dati. Articoli: i dati continui partono dal 16 agosto 2026; sito e canali dal
# 1 agosto 2025 (il backfill dei dati per articolo precedenti non e' richiesto per ora).
GA4_ARTICLES_START ?= 2026-08-16
GA4_SITE_START ?= 2025-08-01

# Definisce il percorso dell'eseguibile Python e Alembic per Windows
VENV = .venv
VENV_BIN = $(VENV)/Scripts
VENV_ALEMBIC = $(VENV_BIN)/alembic

.PHONY: init check-env venv up wait-db migrate install ingest ingest-recent ingest-ga4 ingest-ga4-site ingest-article-scores dbt-build refresh verify-ingestion metabase wait-metabase status down clean help db_docs

## Target principale: esegue l'intera inizializzazione da zero (incluso l'ambiente Python).
## Metabase parte in background insieme a Postgres (stesso docker-compose.yml);
## usa 'make metabase' per attenderlo e vedere le istruzioni di collegamento al DB.
init: check-env venv up wait-db migrate install ingest
	@echo ""
	@echo "==> Inizializzazione completata."
	@echo "==> Metabase in avvio su http://localhost:$(METABASE_PORT) (usa 'make metabase' per attendere che sia pronto)."

## Verifica che .env esista, altrimenti lo crea da .env.example e blocca
## l'esecuzione per dare modo di valorizzare le credenziali.
check-env:
	@if [ ! -f .env ]; then \
		if [ -f .env.example ]; then \
			cp .env.example .env; \
			echo "==> Creato .env da .env.example."; \
			echo "==> Valorizza le credenziali in .env poi rilancia 'make init'."; \
			exit 1; \
		else \
			echo "ERRORE: manca sia .env sia .env.example. Crea .env con POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_PORT."; \
			exit 1; \
		fi \
	fi
	@echo "==> .env presente, procedo."

## Crea l'ambiente virtuale Python e installa i pacchetti da requirements.txt.
## Si attiva automaticamente solo se .venv non esiste o se requirements.txt è stato modificato.
venv: $(VENV)/.venv_created

$(VENV)/.venv_created: requirements.txt
	@echo "==> Creazione ambiente virtuale Python e installazione dipendenze..."
	@if [ ! -d "$(VENV)" ]; then python -m venv $(VENV); fi
	@$(VENV_BIN)/python -m pip install --upgrade pip
	@$(VENV_BIN)/pip install -r requirements.txt
	@echo "" > $(VENV)/.venv_created
	@echo "==> Ambiente virtuale pronto."

## Avvia i container Postgres e Metabase in background.
up: check-env
	@echo "==> Avvio container Postgres e Metabase..."
	docker compose up -d

## Attende che Postgres sia pronto ad accettare connessioni prima di
## procedere con Alembic. Usa pg_isready dentro il container stesso.
wait-db:
	@echo "==> Attendo che Postgres sia pronto..."
	@timeout=30; \
	until docker compose exec -T postgres pg_isready -U $(POSTGRES_USER) -d $(POSTGRES_DB); do \
		timeout=$$((timeout - 1)); \
		if [ $$timeout -le 0 ]; then \
			echo "ERRORE: Postgres non pronto dopo 30s. Controlla 'docker compose logs postgres'."; \
			exit 1; \
		fi; \
		sleep 1; \
	done
	@echo "==> Postgres pronto."

## Applica le migration Alembic usando l'eseguibile dell'ambiente virtuale.
## Rimane nella root del progetto per trovare correttamente 'alembic.ini'.
migrate: venv
	@echo "==> Applico le migration Alembic..."
	DATABASE_URL=$(DATABASE_URL) $(VENV_ALEMBIC) upgrade head

## Installa le dipendenze Node del client WP, solo se node_modules manca
## o package.json e' piu recente (npm ci e' no-op veloce altrimenti).
install:
	@echo "==> Installo dipendenze Node..."
	cd wp_client && /ucrt64/bin/node /ucrt64/lib/node_modules/npm/bin/npm-cli.js install

## Esegue l'ingestion completa da WP REST API a Postgres passando anche il limite di pagine.
ingest:
	@echo "==> Eseguo ingestion articoli (limite pagine: $(MAX_PAGES))..."
	cd wp_client && DATABASE_URL=$(DATABASE_URL) MAX_PAGES=$(MAX_PAGES) /ucrt64/bin/node ingest-articles.js


## Esegue l'ingestion GA4: per ogni giorno del range richiesto (default:
## ultimi GA4_DAYS giorni) interroga la Data API con start=end=giorno e
## scrive in fact_ga4_daily (formato long) con upsert idempotente su
## (article_id, metric_date, metric_name). Range esplicito via GA4_ARGS.
ingest-ga4: check-env venv up wait-db migrate
	@echo "==> Eseguo ingestion GA4 ($(GA4_ARGS))..."
	cd ga4_client && DATABASE_URL=$(DATABASE_URL) GA4_PROPERTY_ID=$(GA4_PROPERTY_ID) ../$(VENV_BIN)/python ingest_ga4.py $(GA4_ARGS)
	
## Ingestione incrementale degli articoli recenti da WP REST API (si ferma agli
## articoli gia' presenti). Da lanciare prima di ingest-ga4: GA4 aggancia le
## pagine agli articoli tramite articles_dim.
ingest-recent: check-env up wait-db migrate
	@echo "==> Eseguo ingestion incrementale articoli..."
	cd wp_client && DATABASE_URL=$(DATABASE_URL) INCREMENTAL=1 MAX_PAGES=$(MAX_PAGES) /ucrt64/bin/node ingest-articles.js

## Ingestione GA4 di totali di sito, canali (sessionDefaultChannelGroup) e utenti
## unici su settimana/mese. Scrive anche in etl_run_log, una riga per fonte.
ingest-ga4-site: check-env venv up wait-db migrate
	@echo "==> Eseguo ingestion GA4 sito/canali/periodi ($(GA4_SITE_ARGS))..."
	cd ga4_client && DATABASE_URL=$(DATABASE_URL) GA4_PROPERTY_ID=$(GA4_PROPERTY_ID) ../$(VENV_BIN)/python ingest_ga4_site.py $(GA4_SITE_ARGS)

## Score editoriale per settimana in fact_article_score_period (metodo balanced-v2).
## Di default carica le settimane complete mancanti dal primo giorno con articoli.
## Backfill o ricalcolo di un range: make ingest-article-scores ARTICLE_SCORE_ARGS="--start 2026-08-17 --end 2026-10-18"
ARTICLE_SCORE_ARGS ?= --auto --floor $(GA4_ARTICLES_START)

ingest-article-scores: check-env venv up wait-db migrate
	@echo "==> Eseguo ingestion score editoriale per periodo ($(ARTICLE_SCORE_ARGS))..."
	cd ga4_client && DATABASE_URL=$(DATABASE_URL) GA4_PROPERTY_ID=$(GA4_PROPERTY_ID) ../$(VENV_BIN)/python article_score_job.py $(ARTICLE_SCORE_ARGS)

## Costruisce e testa i modelli dbt (staging, intermediate, marts). Se la cartella
## dbt/ non esiste ancora salta con un avviso, cosi' 'make refresh' resta usabile.
dbt-build:
	@if [ -d dbt ]; then \
		echo "==> dbt build..."; \
		cd dbt && ([ -d dbt_packages ] || ../$(VENV_BIN)/dbt deps --profiles-dir .) && \
		../$(VENV_BIN)/dbt build --profiles-dir . --vars "{ga4_articles_start: '$(GA4_ARTICLES_START)', ga4_site_start: '$(GA4_SITE_START)'}"; \
	else \
		echo "==> dbt/ non ancora creata: salto dbt build."; \
	fi

## Aggiornamento giornaliero completo, in quest'ordine: articoli, GA4 per articolo, GA4
## sito/canali/periodi, poi dbt. GA4 gira in modalita' --auto: guarda cosa c'e' nel DB e
## carica da solo i giorni mancanti (dopo un fermo recupera tutto) piu' gli ultimi 3 giorni.
## I passi sono indipendenti: se uno fallisce gli altri girano comunque, cosi' un problema di
## WordPress non blocca GA4 e viceversa; il codice di uscita e' non zero se qualcosa e' fallito
## e mart_data_health lo segnala nel dashboard.
## GA4_ARGS e GA4_SITE_ARGS vanno passati espliciti: l'export globale in cima al file li
## propaga gia' espansi ai sub-make e un override come GA4_DAYS=3 verrebbe ignorato.
refresh:
	@rc=0; \
	$(MAKE) ingest-recent || rc=1; \
	$(MAKE) ingest-ga4 GA4_ARGS="--auto --floor $(GA4_ARTICLES_START)" || rc=1; \
	$(MAKE) ingest-ga4-site GA4_SITE_ARGS="--auto --floor $(GA4_SITE_START)" || rc=1; \
	$(MAKE) ingest-article-scores || rc=1; \
	$(MAKE) dbt-build || rc=1; \
	if [ $$rc -ne 0 ]; then echo "==> refresh terminato con errori (vedi sopra)"; fi; \
	exit $$rc

## Esegue le query di verifica post-ingestion (conteggi, gerarchia categorie,
## controlli di idempotenza) e stampa i risultati a schermo. Non modifica
## dati: e' pensato per essere lanciato dopo 'make ingest' o 'make init',
## specialmente dopo una run di test con MAX_PAGES basso.
verify-ingestion:
	@echo "==> Eseguo query di verifica post-ingestion..."
	docker compose exec -T postgres psql -U taxidrivers -d taxidrivers -f //app/scripts/sql/verifiche_post_ingestion.sql

## Genera con tbls la documentazione del DB (pagine Markdown per tabella + ER)
## da condividere con i designer della dashboard. Non modifica dati.
## Il container raggiunge Postgres sulla porta esposta dall'host (host.docker.internal).
db_docs: up wait-db migrate
	@echo "==> Genero la documentazione del DB in $(DOCS_DIR)..."
	MSYS_NO_PATHCONV=1 docker run --rm \
		-v "$(CURDIR)":/work -w //work \
		-e TBLS_DSN="postgres://$(POSTGRES_USER):$(POSTGRES_PASSWORD)@host.docker.internal:$(POSTGRES_PORT)/$(POSTGRES_DB)?sslmode=disable" \
		$(TBLS_IMAGE) doc --rm-dist
	@echo "==> Fatto: $(DOCS_DIR)/README.md"

## Attende che Metabase risponda su /api/health prima di considerarlo utilizzabile.
## Il primo avvio puo' richiedere fino a un minuto (inizializzazione del DB applicativo interno).
wait-metabase:
	@echo "==> Attendo che Metabase sia pronto..."
	@timeout=90; \
	until docker compose exec -T metabase curl --fail -s http://localhost:3000/api/health >/dev/null 2>&1; do \
		timeout=$$((timeout - 2)); \
		if [ $$timeout -le 0 ]; then \
			echo "ERRORE: Metabase non pronto dopo 90s. Controlla 'docker compose logs metabase'."; \
			exit 1; \
		fi; \
		sleep 2; \
	done
	@echo "==> Metabase pronto."

## Avvia (se necessario) Postgres e Metabase e attende che Metabase sia raggiungibile.
## Al primo avvio va completato il setup dal browser (http://localhost:$(METABASE_PORT)):
## crea l'utente admin, poi aggiungi come data source il Postgres di questo progetto
## usando host "postgres" (nome del servizio sulla rete Docker interna, non "localhost"),
## porta 5432, e database/utente/password come da .env.
metabase: check-env up wait-metabase
	@echo ""
	@echo "==> Metabase pronto: apri http://localhost:$(METABASE_PORT)"
	@echo "    Data source Postgres -> host: postgres | porta: 5432 | db: $(POSTGRES_DB) | utente: $(POSTGRES_USER)"

## Mostra lo stato dei container (Postgres e Metabase, incluso lo stato di health) e la revisione Alembic corrente.
status:
	@echo "==> Stato container:"
	@docker compose ps
	@echo ""
	@echo "==> Revisione Alembic corrente:"
	@DATABASE_URL=$(DATABASE_URL) $(VENV_ALEMBIC) current

## Ferma i container (mantiene i dati sui volumi, inclusa la configurazione di Metabase).
down:
	docker compose down

## Ferma i container e rimuove anche i volumi dati (Postgres + Metabase) e l'ambiente virtuale.
clean:
	@echo "ATTENZIONE: questo cancella i dati nei volumi Postgres/Metabase e l'ambiente virtuale Python."
	@printf "Confermi? [y/N] "; \
	read ans; \
	if [ "$$ans" = "y" ] || [ "$$ans" = "Y" ]; then \
		docker compose down -v; \
		rm -rf $(VENV); \
		echo "==> Container, volumi e .venv rimossi."; \
	else \
		echo "==> Annullato."; \
	fi

help:
	@echo "Target disponibili:"
	@echo "  make init              - inizializzazione completa (check-env + venv + up + wait-db + migrate + install + ingest)"
	@echo "  make venv              - crea l'ambiente virtuale e installa requirements.txt"
	@echo "  make up                - avvia i container Postgres e Metabase"
	@echo "  make wait-db           - attende che Postgres sia pronto"
	@echo "  make migrate           - applica le migration Alembic (crea venv se manca)"
	@echo "  make install           - installa le dipendenze Node"
	@echo "  make ingest            - esegue l'ingestion articoli (richiede schema gia migrato)"
	@echo "  make ingest-recent     - ingestion incrementale degli articoli recenti (da lanciare prima di ingest-ga4)"
	@echo "  make ingest-ga4        - esegue l'ingestion GA4 (ultimi GA4_DAYS giorni, default 30; GA4_ARGS per range esplicito)"
	@echo "  make ingest-ga4-site   - ingestion GA4 di sito, canali e utenti su periodo (GA4_SITE_ARGS, default ultimi 3 giorni)"
	@echo "  make ingest-article-scores - score editoriale per settimana (ARTICLE_SCORE_ARGS, default settimane mancanti)"
	@echo "  make dbt-build         - costruisce e testa i modelli dbt (salta se dbt/ non esiste)"
	@echo "  make refresh           - aggiornamento giornaliero: articoli, GA4, sito/canali, dbt"
	@echo "  make verify-ingestion  - esegue le query di verifica post-ingestion (scripts/verifiche_post_ingestion.sql)"
	@echo "  make db_docs           - genera la documentazione del DB con tbls in docs/db/ (per i designer)"
	@echo "  make metabase          - avvia/attende Metabase e mostra le info per collegare il data source Postgres"
	@echo "  make wait-metabase     - attende solo che Metabase risponda su /api/health"
	@echo "  make status            - mostra stato container e revisione Alembic"
	@echo "  make down              - ferma i container (mantiene i dati)"
	@echo "  make clean             - reset completo (cancella volumi DB/Metabase e cartella .venv - chiede conferma)"