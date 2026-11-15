# Infrastruttura dati di Taxi Drivers Lab

Documento di insieme: cosa c'è, dove sta, come i dati si muovono dalla fonte al consumatore, come si gestisce e cosa non è ancora a posto. Fotografia all'**8 novembre 2026**. I numeri sono letti dal database e dal pianificatore di Windows quel giorno.

Chi cerca un dettaglio trova il rimando al documento specifico in §12. Questo documento non li sostituisce: li collega.

## 1. In breve

Taxi Drivers Lab è un piccolo warehouse analitico su un solo PC Windows, per il sito taxidrivers.it. Cinque pezzi:

1. **Fonti.** WordPress (articoli e categorie), Google Analytics 4 (traffico), fonti esterne di attenzione sui titoli (Wikipedia, TMDB, IMDb, Google Trends, YouTube, Trakt, Rotten Tomatoes).
2. **Ingestione.** Script Node.js (WordPress) e Python (GA4, score, segnali) che scrivono in Postgres in modo idempotente.
3. **Warehouse.** Postgres 16 in Docker; schema versionato con Alembic (SQL puro); trasformazioni con dbt in tre livelli (`staging`, `intermediate`, `marts`).
4. **Orchestrazione.** `make refresh`, lanciato ogni giorno dall'Utilità di pianificazione di Windows.
5. **Consumo.** Metabase, il dashboard previsto per i tab Contenuti, Panoramica e Acquisizione, report Excel e documenti editoriali.

Non c'è un cloud, né un orchestratore, né un ambiente di produzione separato: tutto gira sul PC dello sviluppatore. Le conseguenze sono in §10.

## 2. Mappa

```
 FONTI                    INGESTIONE                         WAREHOUSE (Postgres 16, Docker)                 CONSUMO
 ─────                    ──────────                         ───────────────────────────────                 ───────
 WordPress REST API ──► wp_client/ingest-articles.js ──► articles_dim, categories_dim,
 (taxidrivers.it)         (Node, MSYS2)                     articles_categories
                                                                    │
 GA4 Data API ────────► ga4_client/ingest_ga4.py ───────► fact_ga4_daily (articolo x giorno x metrica)
 (proprietà 394327334)  ga4_client/ingest_ga4_site.py ──► fact_ga4_site_daily, fact_ga4_channel_daily,
                        ga4_client/article_score_job.py   fact_ga4_site_period, fact_article_score_period
                                                                    │                                       ┌─► Metabase (:3000)
 Wikipedia · TMDB ·     scripts/trend_best_of.py ───────► fact_article_signal                               ├─► Dashboard Contenuti /
 IMDb · Google Trends · (+ external_trend.py,                       │                                       │   Panoramica / Acquisizione
 YouTube · Trakt ·        signal_sources.py)                        ▼                                       │   (brief frontend)
 Rotten Tomatoes                                         dbt: staging ► intermediate ► marts ──────────────┤
                                                         (schemi staging / intermediate / marts)            ├─► Excel "best of trend"
                                                                    ▲                                       ├─► Midreport e report settimanale
 etl_run_log ◄── ogni ingestione scrive una riga ───────────────────┘ ► marts.mart_data_health            └─► Notebook di analisi
```

## 3. Componenti

| Pezzo | Tecnologia | Dove | Note |
| --- | --- | --- | --- |
| Database | Postgres 16 | `docker-compose.yml`, container `td_postgres`, porta host **5437** | Volume `postgres_data`. Cartella `scripts/` montata in sola lettura |
| Migrazioni | Alembic, SQL puro | `alembic/`, `alembic.ini` | 6 revisioni (0001–0006), nessun ORM |
| Ingestione WordPress | Node.js (`wpapi`, `pg`) | `wp_client/` | Esegue sotto MSYS2 UCRT64 (`/ucrt64/bin/node`) |
| Ingestione GA4 e score | Python 3.12 | `ga4_client/` | OAuth2 "installed app"; token in `ga4_client/token.json` (non versionato) |
| Segnali esterni e best of | Python | `scripts/trend_best_of.py`, `external_trend.py`, `signal_sources.py` | Si lancia a mano. Vedi [data_product_best_of_trend.md](data_product_best_of_trend.md) |
| Trasformazioni | dbt-core 1.12, dbt-postgres 1.10 | `dbt/` | Profilo `taxidrivers`, target `dev`, 4 thread; credenziali da variabili d'ambiente |
| Orchestrazione | GNU Make | `Makefile` | Target principale `refresh` |
| Pianificazione | Utilità di pianificazione di Windows | Attività "TaxiDrivers ETL giornaliero" → `scripts/run_refresh.cmd` → `run_refresh.sh` | Avvia Docker Desktop se non risponde |
| BI | Metabase (immagine `latest`) | container `td_metabase`, porta 3000 | Database applicativo H2 su volume `metabase_data` |
| Accesso ai dati da Python | pandas + SQLAlchemy core + psycopg2 | `data_access/db.py`, `data_access/metrics.py` | `query_df` per le letture, `get_connection` per le scritture |
| Documentazione del DB | tbls | `tbls.yml`, `make db_docs`, cartella `dbdoc/` | Pagine per tabella con diagramma ER |
| Fotografia del DB | Python | `db_snapshot.py` | Sola lettura: tabelle, colonne, conteggi |
| NLP (sperimentale) | spaCy | `nlp/topic_extraction/` | Pulizia HTML e lemmatizzazione; l'estrazione dei topic non è implementata |
| Test | pytest, test dbt, test Node | `tests/`, `dbt/tests/` | Vedi §9 |

## 4. Fonti e ingestioni

| Fonte | Script | Scrive in | Cosa carica | Come decide cosa caricare |
| --- | --- | --- | --- | --- |
| WordPress REST API | `wp_client/ingest-articles.js` (`make ingest`, `make ingest-recent`) | `articles_dim`, `categories_dim`, `articles_categories` | Articoli pubblicati, categorie (solo la tassonomia standard `category`), legami | Completa o incrementale (`INCREMENTAL=1`: si ferma al primo articolo già presente) |
| GA4 per articolo | `ga4_client/ingest_ga4.py` | `fact_ga4_daily` | 8 metriche per articolo e giorno: `active_users`, `screen_page_views`, `sessions`, `engaged_sessions`, `engagement_rate`, `bounce_rate`, `average_session_duration`, `user_engagement_duration` | `--auto --floor 2026-08-16`: giorni senza righe, più gli ultimi 3. Una query GA4 per giorno, tetto di 60 giorni per esecuzione |
| GA4 sito e canali | `ga4_client/ingest_ga4_site.py` | `fact_ga4_site_daily`, `fact_ga4_channel_daily`, `fact_ga4_site_period` | Totali di sito, per gruppo di canali (`sessionDefaultChannelGroup`), utenti unici su settimana e mese | `--auto --floor 2025-08-01`. I canali si riscrivono con DELETE + INSERT |
| GA4 → score editoriale | `ga4_client/article_score_job.py` | `fact_article_score_period` | Score, rank e segmento (`balanced-v2`) per articolo e settimana completa | Settimane complete mancanti dal 2026-08-16 |
| Fonti esterne | `scripts/trend_best_of.py` | `fact_article_signal` + cache in `output/cache/` | Segnali di attenzione per opera, formato lungo (`signals-v1`) | A mano, su una finestra scelta |
| Midreport top 100 | `ga4_client/midreport_client.py` | Nessuna tabella: scrive un file Excel dal template | Top N articoli di un intervallo | A mano |

**Aggancio pagina GA4 → articolo** (`ga4_service.resolve_page_path`): prima il prefisso numerico del permalink (`/<article_id>/<categoria>/<slug>.html`), poi lo slug in `articles_dim`. Le pagine non articolo (home, categorie) si scartano. La copertura dell'aggancio è nel mart di salute (§7).

**Esclusioni editoriali.** Gli articoli "streaming gratis" e "5 attrici…pornostar" non compaiono mai in top e selezioni. L'unica fonte della regola è `EXCLUDED_TITLE_PATTERNS` in `ga4_client/midreport_client.py`; la riusano il best of e il midreport.

## 5. Warehouse: schema `public` (raw)

Tutte le scritture sono **upsert idempotenti** (`ON CONFLICT … DO UPDATE`): rilanciare un job non duplica righe.

| Tabella | Grain | Righe (8/11) | Copertura | Scritta da | Migrazione |
| --- | --- | --- | --- | --- | --- |
| `articles_dim` | un articolo | 56.158 | 2007 → 08/11/2026 | WordPress | 0001 |
| `categories_dim` | una categoria | 282 | — | WordPress | 0001 |
| `articles_categories` | legame articolo–categoria | 65.195 | — | WordPress | 0001 |
| `fact_ga4_daily` | articolo × giorno × metrica | 721.760 | giorni isolati dal 15/01/2025; continua dal 16/08/2026 al 07/11/2026 | `ingest_ga4.py` | 0002, 0003 |
| `fact_ga4_site_daily` | giorno | 464 | 01/08/2025 → 07/11/2026 | `ingest_ga4_site.py` | 0004 |
| `fact_ga4_channel_daily` | giorno × canale | 2.647 | 01/08/2025 → 07/11/2026 | `ingest_ga4_site.py` | 0004 |
| `fact_ga4_site_period` | settimana o mese | — | utenti unici di periodo | `ingest_ga4_site.py` | 0004 |
| `fact_article_score_period` | articolo × periodo × versione | 4.167 | settimane dal 17/08 al 26/10/2026 | `article_score_job.py` | 0005 |
| `fact_article_signal` | articolo × fonte × metrica × data × finestra × versione | 1.350 | rilevazione del 06/11/2026 | `trend_best_of.py` | 0006 |
| `etl_run_log` | un'esecuzione di una fonte | — | `running` → `success` / `failed` | gli script di ingestione | 0004 |
| `fact_wp_engagement_weekly` | articolo × settimana | **0** | nessuno script la popola | — | 0001 |
| `fact_ga4_daily_legacy_pagepath` | archivio del vecchio formato | 0 | forensics e rollback | — | 0003 |
| `alembic_version` | — | 1 | revisione corrente `0006_fact_article_signal` | Alembic | — |

Anche le viste `fact_ga4_daily_matched` e `fact_ga4_unmatched` (migrazione 0002) risalgono al vecchio schema.

**Scelte di modello.**

- **Formato lungo** per i fatti per articolo (`fact_ga4_daily`, `fact_article_signal`): una metrica nuova è una riga, non una colonna né una migrazione.
- **Formato largo** per i totali di sito e canale (poche righe al giorno); i rapporti si ricalcolano a valle e non si salvano.
- **Vincoli minimi nel raw**: solo ciò che non può essere vero (conteggi negativi, intervalli invertiti). Le invarianti di dominio vivono nei test dbt con severità `warn`, così una revisione dei dati GA4 non blocca il caricamento.
- **Versione del metodo** nelle tabelle derivate (`balanced-v2` per lo score, `signals-v1` per i segnali): versioni diverse convivono, il confronto storico filtra per versione.
- **Gli utenti unici di periodo non si ricavano dai giornalieri**: `active_users` giornaliero non è sommabile. Per questo esistono `fact_ga4_site_period` e il campo `active_users` di `fact_article_score_period`.
- **Fuso orario**: le date di pubblicazione si leggono in `Europe/Rome`. Convertire cambia il giorno a 1.331 articoli su 54.845.

## 6. Trasformazioni dbt

Progetto `dbt/` (nome `taxidrivers`), `+persist_docs` attivo (descrizioni delle colonne nel database, visibili in Metabase).

| Livello | Schema | Materializzazione | Contenuto |
| --- | --- | --- | --- |
| `staging` | `staging` | vista | 7 modelli: articoli, categorie, legami, GA4 per articolo, sito (giorno e periodo), canali. Pulizia e tipi, nessuna logica di business |
| `intermediate` | `intermediate` | vista (5) + seed | Sezione primaria di ogni articolo, spine delle settimane, copertura, categorie per sezione, articolo × giorno |
| `marts` | `marts` | tabella (9) + 2 seed; `mart_data_health` è una vista | `dim_date`, `dim_article`, `mart_article_daily`, `mart_article_weekly`, `mart_section_weekly`, `mart_content_weekly`, `mart_site_daily`, `mart_site_period`, `mart_channel_daily`, `mart_data_health` |

Seed (CSV in `dbt/seeds/`): `dim_section` (14 sezioni, compresa `non_classificato`), `dim_channel` (etichette dei canali), `section_category_map` (categorie → sezione, con `include_children`).

Variabili di progetto: `ga4_articles_start` (2026-08-16), `ga4_site_start` (2025-08-01), `provisional_days` (2). Il Makefile le definisce una volta (`GA4_ARTICLES_START`, `GA4_SITE_START`) e le passa sia all'ETL sia a dbt, così non si disallineano.

**Regole dei mart.**

- I mart per articolo sono **sparsi**: l'assenza di riga vale zero. Densificarli darebbe decine di milioni di righe di zeri.
- I mart di sito e di sezione sono **densi** (partono da `dim_date`).
- I confronti ammessi sono a spostamento fisso: `_py` (anno prima, 364 giorni o 52 settimane), `_p7` (7 giorni prima), `_prev` (settimana o mese prima). Sono `null` dove manca lo storico: per articolo e sezione il confronto con l'anno prima resta `null` fino ad agosto 2027.
- Nei canali si sommano solo le sessioni: gli utenti attivi per canale non si sommano.

**Test.** 5 test singolari in `dbt/tests/` (riconciliazione articoli–sito, canali–sito giornaliero e settimanale, utenti di periodo entro i limiti dei giornalieri, visualizzazioni articolo non sopra il sito) più i test di schema nei file `.yml`. Tolleranza di riconciliazione dei canali: 5% al giorno, 1% sulla settimana.

## 7. Orchestrazione e salute dei dati

**`make refresh`** esegue, in ordine e **indipendenti** (un passo che fallisce non ferma gli altri; il codice di uscita finale è diverso da zero se uno è fallito):

1. `ingest-recent`: articoli nuovi da WordPress;
2. `ingest-ga4 --auto`: GA4 per articolo;
3. `ingest-ga4-site --auto`: sito, canali, periodi;
4. `ingest-article-scores`: score editoriale delle settimane complete mancanti;
5. `dbt-build`: modelli e test (circa 20 secondi).

Ogni target ricontrolla container e migrazioni (`check-env`, `up`, `wait-db`, `migrate`), quindi `refresh` porta anche lo schema all'ultima revisione.

**Backfill dinamico.** Gli script GA4 non si fidano di "ieri": guardano cosa c'è nelle tabelle e caricano i giorni senza righe dal `floor` in poi, più gli ultimi 3 giorni (GA4 rivede i dati recenti). Dopo un fermo la prima esecuzione utile recupera tutto; per gli articoli al massimo 60 giorni per volta. Per estendere lo storico basta anticipare `GA4_ARTICLES_START` o `GA4_SITE_START` nel Makefile.

**Pianificazione.** Attività "TaxiDrivers ETL giornaliero", con "avvia appena possibile" se il PC era spento. Il log di ogni giorno è in `logs/refresh_AAAA-MM-GG.log`.

**Salute dei dati.** Due strumenti:

- `etl_run_log`: una riga per fonte e per esecuzione. Una riga rimasta `running` indica un job interrotto.
- `marts.mart_data_health`: una riga per fonte (`ga4_articles`, `ga4_site_daily`, `ga4_channel_daily`, `ga4_site_period`, `wp_articles`) con ultimo giorno coperto, giorni mancanti negli ultimi 30, ore dall'ultimo caricamento, stato `ok`/`warn`/`error`. Per `ga4_articles` riporta anche `matching_coverage`: la quota delle visualizzazioni di sito spiegata dalle pagine agganciate a un articolo, sugli ultimi 30 giorni chiusi. All'8 novembre è **70,8%**.

Uso e rimedi quotidiani: [etl_giornaliero.md](etl_giornaliero.md).

## 8. Consumo

| Consumatore | Cosa legge | Stato |
| --- | --- | --- |
| **Metabase** (`localhost:3000`) | schema `marts` (e raw per esplorazione); host `postgres`, porta 5432 dentro la rete Docker | Attivo |
| **Dashboard Contenuti / Panoramica / Acquisizione** | i mart come contratto; descritti in [brief_frontend_contenuti_panoramica.md](brief_frontend_contenuti_panoramica.md) | Livello dati costruito; la parte grafica è un lavoro a parte |
| **Best of trend** (Excel) | `fact_ga4_daily` + fonti esterne; scrive `fact_article_signal` | A mano. [data_product_best_of_trend.md](data_product_best_of_trend.md) |
| **Midreport top 100** | GA4 diretto + `articles_dim` | A mano, via `midreport_client.py` |
| **Report settimanale (WhatsApp) e midreport** | file Excel `top_articles_by_category`, score editoriale | Fuori da questo repo |
| **Notebook** | `notebooks/` (analisi delle keyword, analisi Venezia) | Esplorativi |
| **`editorial_dashboard`** | container Docker sulla porta 8050 | In esecuzione sul PC; **non è gestito da questo repo** e non so da dove legga |

## 9. Test

| Dove | Cosa copre |
| --- | --- |
| `tests/test_ga4_site_tables.py`, `test_backfill_plan.py` | tabelle di sito e logica del backfill |
| `tests/test_article_scoring.py`, `test_article_score_writer.py` | score editoriale e scrittura |
| `tests/test_category_mapping.py`, `test_midreport_exclusions.py` | mappa categorie del midreport ed esclusioni |
| `tests/test_external_trend.py` | fonti esterne e best of, con rete simulata |
| `tests/test_fact_ga4_daily_long_format.py` | formato lungo di `fact_ga4_daily`; richiede `DATABASE_URL` e un database vero |
| `tests/test_ga4_service.js` | service layer GA4 in Node |
| `dbt/tests/` e `.yml` dei modelli | riconciliazioni e vincoli sui dati |

Da root: `.venv\Scripts\python.exe -m pytest tests/test_external_trend.py tests/test_midreport_exclusions.py` (senza database). I test con database richiedono `DATABASE_URL` nell'ambiente.

## 10. Configurazione, segreti e rischi operativi

**Variabili** (file `.env`, ignorato da git; `.env.example` ne elenca i nomi): `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`, `MAX_PAGES`, `GA4_PROPERTY_ID`, `TMDB_API_KEY`, e opzionali `YOUTUBE_API_KEY`, `TRAKT_CLIENT_ID`.

**Segreti fuori da git**: `.env`, `ga4_client/client_secrets.json`, `ga4_client/token.json`, `backups/`, `logs/`.

**Rischi noti, in ordine di gravità.**

1. **Un solo PC.** Se è spento i dati non si aggiornano (poi recupera il backfill). Dal 15 novembre un backup automatico gira dopo ogni refresh (§10 bis), ma **finisce sullo stesso disco**: protegge da errori e da cancellazioni, non da un guasto del disco o del PC. Per quello serve `BACKUP_COPY_DIR` su un altro supporto. Resta anche il vecchio dump manuale `backups/td_20261019.sql` (435 MB, dentro OneDrive).
2. **La password del database compare nei log.** `make` stampa il comando con `DATABASE_URL` completo e `run_refresh.sh` lo salva in `logs/refresh_*.log`. La cartella è ignorata da git, ma i log restano leggibili sul disco (e la cartella è dentro OneDrive). Il valore attuale è anche quello predefinito di esempio.
3. **Metabase su H2 embedded.** Dashboard e utenti stanno in un file su volume Docker, senza backup; la documentazione di Metabase sconsiglia H2 per un uso serio.
4. **Immagine `metabase/metabase:latest`.** Un aggiornamento automatico può cambiare il comportamento senza avviso.
5. **Token GA4 su disco.** Se Google lo invalida, l'ingestione GA4 fallisce; si rinnova da un terminale interattivo.
6. **Il repo è dentro OneDrive.** Sincronizza anche `output/`, `logs/` e le cache; possibili conflitti con i file aperti da Docker o da Python.

## 10 bis. Backup e ripristino

**Cosa.** `scripts/backup_db.sh` fa un `pg_dump` completo (SQL, compresso) del database dal container `td_postgres`. Parte da solo alla fine di `scripts/run_refresh.sh`, anche se il refresh è fallito; se il backup fallisce il codice di uscita diventa 4 e l'errore è nel log del giorno. A mano: `bash scripts/backup_db.sh`.

**Dove.** `C:\Users\manuel.deluzi\Backups\taxidrivers\td_AAAAMMGG_HHMMSS.sql.gz`, fuori da OneDrive. Cartella e soglie si cambiano con le variabili `BACKUP_DIR`, `BACKUP_KEEP_DAILY_DAYS`, `BACKUP_KEEP_WEEKLY_DAYS`.

**Conservazione.** Giornalieri 14 giorni; quelli della domenica (suffisso `_weekly`) 90 giorni. Il primo backup pesa circa 140 MB.

**Controlli.** Il file si scrive come `.part` e prende il nome definitivo solo dopo: gzip integro, almeno 1 MB, riga finale di `pg_dump` presente. Un dump a metà non sostituisce mai uno buono. Le credenziali sono quelle del container: nessuna password sulla riga di comando o nei log.

**Seconda copia.** Impostando `BACKUP_COPY_DIR` (disco esterno, cartella di rete) il file viene copiato anche lì. Se la cartella non è raggiungibile il backup locale resta valido e il log lo segnala.

**Ripristino** (in un database nuovo, senza toccare quello in uso; provato il 15 novembre: tabelle identiche all'originale, nessun errore):

```bash
docker exec td_postgres sh -c 'createdb -U "$POSTGRES_USER" td_ripristino'
gzip -dc /c/Users/manuel.deluzi/Backups/taxidrivers/<file>.sql.gz | docker exec -i td_postgres sh -c 'psql -U "$POSTGRES_USER" -d td_ripristino -q'
```

Per sostituire il database in uso, fermare prima l'ETL (disabilitare l'attività pianificata), poi eliminare e ricreare il database e ripetere il ripristino su di esso. Dopo il ripristino lanciare `make migrate`.

**Non coperto.** Il database di Metabase (dashboard e utenti) sta su un volume Docker a parte e non è nel dump. Il backup non sta in un'altra macchina finché non si imposta `BACKUP_COPY_DIR`.

## 11. Stato al 8 novembre 2026 e punti aperti

| Tema | Stato |
| --- | --- |
| Ultimo refresh | Partito l'8/11 alle 10:17 (ora locale). Articoli, sito e canali risultano `success`. Alla verifica la riga `ga4_site_period` era ancora `running` e il pianificatore riportava come esito 0xC000013A (processo terminato dall'esterno): **da controllare se è in corso o interrotto**. Una riga rimasta `running` non si chiude da sola |
| Orario dell'attività | Il pianificatore ha **06:30**; `etl_giornaliero.md` e la guida dicono 07:30. Va riallineato uno dei due |
| Salute dei dati | Tutte le fonti `ok`; `ga4_site_period` copre fino al 2 novembre (i periodi si chiudono a fine settimana o mese) |
| Aggancio pagine GA4 → articoli | Gli articoli spiegano il 70,8% delle visualizzazioni di sito. Il resto (circa 29%) sono pagine non articolo (home, categorie, pagine di servizio) e articoli non agganciati; non è stato misurato quanto pesa ciascuno |
| `fact_wp_engagement_weekly` | Vuota: commenti e modifiche non sono disponibili |
| Articoli modificati dopo l'import | Non vengono riletti (`ingest-recent` carica solo i nuovi) |
| Dati per articolo prima del 16/08/2026 | Nessun backfill: il confronto annuale per articolo e sezione è `null` fino ad agosto 2027 |
| Tassonomie WordPress personalizzate | Mai lette; solo `category` |
| `best_of_trend` | Non è in `make refresh`; i segnali si accumulano solo quando lo si lancia |
| Documenti non allineati | `STORAGE.md` descrive solo Postgres e la migrazione 0001; `etl_giornaliero.md` e la guida backend riportano l'orario 07:30 e i conteggi del 19 ottobre; `tbls.yml` scrive in `docs/db` ma la cartella è `dbdoc/` |
| `snapshots.csv`, `tmdb_popularity.csv` | Storico dei segnali ancora su file in `output/cache/`, in parallelo a `fact_article_signal` |

## 12. Dove trovare il resto

| Documento | Contenuto |
| --- | --- |
| [etl_giornaliero.md](etl_giornaliero.md) | Funzionamento quotidiano, verifica, rimedi, gestione dell'attività |
| [guida_backend_contenuti_panoramica.md](guida_backend_contenuti_panoramica.md) | Costruzione del livello dati e scelte rispetto al blueprint |
| [brief_frontend_contenuti_panoramica.md](brief_frontend_contenuti_panoramica.md) | Contratto dei mart per chi disegna il dashboard |
| [data_product_best_of_trend.md](data_product_best_of_trend.md) | Best of trend, fonti esterne e `fact_article_signal` |
| [metodologia_profilo_stile.md](metodologia_profilo_stile.md) | Profilo di stile del Trend Radar: imitazione dello stile d'autore, metriche di controllo, stilometria |
| `STORAGE.md` | Setup di Postgres e Alembic (parziale, vedi §11) |
| `wp_client/README.md` | Client WordPress |
| `dbdoc/` | Pagine per tabella generate con tbls (`make db_docs`) |

## 13. Cosa farei per primo

In ordine di rapporto tra rischio ridotto e lavoro:

1. ~~Backup automatico di Postgres~~ **Fatto il 15 novembre** (§10 bis). Resta da impostare `BACKUP_COPY_DIR` su un altro supporto e da includere nel backup il database di Metabase.
2. **Togliere la password dai log**: far stampare a `make` solo i nomi delle variabili (prefisso `@` alle ricette) e passare `DATABASE_URL` dall'ambiente.
3. **Chiudere le righe `running`** all'avvio dell'ETL (marcare `failed` quelle più vecchie di un'ora), così `mart_data_health` non resta in dubbio dopo un'interruzione.
4. **Riallineare i documenti** di §11 e lo stesso orario in pianificatore e documentazione.
5. **Pinnare la versione di Metabase** e spostare il suo database applicativo su Postgres (schema separato) per averlo nel backup.
6. **Scomporre il 29% di visualizzazioni non spiegate dagli articoli** (pagine non articolo contro articoli non agganciati) e recuperare questi ultimi.
7. **Portare `best_of_trend` nel refresh**, con una finestra di default, per accumulare lo storico dei segnali, e usare `fact_article_signal` come unica fonte di storico al posto dei CSV.
8. **Controlli automatici di freschezza** con avviso (e-mail o notifica) quando una fonte passa a `warn` o `error`, oggi visibile solo aprendo il dashboard.
