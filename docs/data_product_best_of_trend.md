# Data product · Best of Trend (Sala, Streaming, Festival)

Documento tecnico di definizione del data product e descrizione dell'ETL che lo produce. Stato: **v0.1, prototipo funzionante** (6 novembre 2026). Il codice è in [scripts/trend_best_of.py](../scripts/trend_best_of.py) e [scripts/external_trend.py](../scripts/external_trend.py), i test in [tests/test_external_trend.py](../tests/test_external_trend.py).

---

## 0. Data mesh: cosa ne penso

Il data mesh è soprattutto un modello **organizzativo**: i domini di business possiedono i propri dati, li espongono come prodotti con un proprietario e un contratto, sopra una piattaforma self-service e con regole federate. Ha senso quando ci sono più team che si pestano i piedi su un data warehouse centrale. Qui c'è un solo sviluppatore e un solo consumatore finale: adottarlo "per intero" (più domini, governance federata, un catalogo) sarebbe cerimonia senza beneficio.

Quello che invece vale la pena prendere, e costa poco, è il **pensiero da data product**:

| Principio del mesh | Cosa significa qui, concretamente |
| --- | --- |
| Ownership di dominio | Un nome per ogni prodotto (§1). Chi lo cambia sa chi avvisare |
| Dati come prodotto | Uno scopo, un consumatore, un contratto sull'output (§5), non "un Excel che esce dallo script" |
| Piattaforma self-service | Esiste già: Postgres in Docker, Alembic, dbt, Makefile, `make refresh` (§8) |
| Governance federata | Poche regole comuni scritte una volta: versione del metodo, esclusioni editoriali, fonti esterne, licenze (§9) |

**Raccomandazione.** Trattare questo come un prodotto *consumer-aligned* dentro un unico dominio ("Audience e contenuti"), non come un mesh. Se in futuro arrivano un secondo team o un secondo consumatore (per esempio il dashboard Metabase o il Midreport), si spezzano i prodotti per dominio: la §10 dice dove sono già le cuciture.

---

## 1. Identità del prodotto

| Campo | Valore |
| --- | --- |
| Nome | `best_of_trend` |
| Dominio | Audience e contenuti di taxidrivers.it |
| Tipo | Consumer-aligned: aggrega e interpreta prodotti sorgente per uno scopo editoriale |
| Owner | Manuel De Luzi |
| Versione | 0.1.0 (prototipo) |
| Versione del metodo | non ancora nel codice: proposta `best-of-trend-v1` (vedi §11) |
| Frequenza | A richiesta, su finestra scelta dall'utente |

## 2. Scopo e consumatori

**Problema.** L'articolo "best of" mette insieme i contenuti più in trend di tre categorie (film in sala, streaming, festival). Serve una misura di trend che non dipenda solo dal nostro pubblico, perché altrimenti si premia ciò che il nostro sito ha già spinto.

**Domanda a cui risponde.** *Quali opere, in ciascuna delle tre categorie, hanno oggi più attenzione e più accelerazione?*

**Consumatore.** Chi scrive il best of. L'output è un Excel da leggere, filtrare e commentare; non è pensato per essere riletto da una macchina.

**Cosa non è.** Non è una classifica di qualità, né una previsione, né una misura di redditività del contenuto. L'esito va letto come una *fascia*: sulle views del sito (30–140 a titolo) i punteggi vicini non si distinguono.

## 3. Architettura

```
 WordPress ──► articles_dim, categories_dim, articles_categories ─┐
 GA4 ───────► fact_ga4_daily (formato lungo) ─────────────────────┤
                                                                   ├─► trend_best_of.py ─► Excel
 Wikipedia (it/en) ──► ricerca voce + visite giornaliere ─────────┤      │
 TMDB ───────► ricerca film/serie + popolarità ───────────────────┤      ├─► output/cache/wikipedia.json
 IMDb · Google Trends · YouTube · Trakt · Rotten Tomatoes ────────┘      ├─► output/cache/tmdb_popularity.csv
   (scripts/signal_sources.py, ognuna in colonne proprie)                 ├─► output/cache/<fonte>.json
                                                                          └─► output/cache/snapshots.csv
```

Le prime due righe sono alimentate dall'ETL quotidiano (`make refresh`, §8). Le fonti esterne sono interrogate a ogni esecuzione dello script; le risposte già note restano in cache.

## 4. Input ports (sorgenti)

| Sorgente | Cosa si legge | Chi la produce | Note |
| --- | --- | --- | --- |
| `articles_dim` | titolo, link, data di pubblicazione (fuso Europe/Rome), stato `publish` | `wp_client/ingest-articles.js` | Solo articoli pubblicati |
| `categories_dim`, `articles_categories` | albero delle categorie (ricorsivo) e legami articolo-categoria | stessa ingestione | Radici: in-sala (26), live-streaming-on-demand (25048), festival-di-cinema (20); con `--with-serie-tv` anche le categorie serie (§6) |
| `fact_ga4_daily` | metriche per articolo e giorno: `screen_page_views`, `active_users`, `sessions`, `engaged_sessions`, `user_engagement_duration`, `average_session_duration` | `ga4_client/ingest_ga4.py` | Formato lungo (una riga per articolo, giorno, metrica). `active_users` giornaliero non è sommabile come utenti unici |
| `ga4_client/article_scoring.py` | `score_articles` (score editoriale `balanced-v2`) | codice condiviso col report settimanale | Riuso, non copia |
| `ga4_client/midreport_client.py` | `is_excluded_title` | codice condiviso col Midreport | Esclusioni editoriali |
| Wikipedia API | ricerca (`list=search`), descrizione breve, visite giornaliere (utenti, tutti gli accessi) | Wikimedia | Gratuita, senza chiave, con User-Agent identificativo |
| TMDB API | `search/multi` in `it-IT`: id, tipo, titolo, data, popolarità; `external_ids` per l'id IMDb | The Movie Database | Chiave in `TMDB_API_KEY` nel `.env` (non tracciato da git) |
| IMDb dataset | `title.ratings.tsv.gz` (~9 MB, aggiornato ogni giorno): numero di voti e voto medio | datasets.imdbws.com | Senza chiave. Abbinamento via TMDB (id IMDb), quindi serve la chiave TMDB. **Solo uso non commerciale** |
| Google Trends | Interesse di ricerca in Italia nella finestra, rapportato al termine ancora "trailer" | `pytrends` (accesso **non ufficiale**) | Senza chiave. Una richiesta per titolo, solo titoli in classifica. Se Google risponde con errori (429) la fonte si ferma per quell'esecuzione |
| YouTube Data API v3 | Visualizzazioni del trailer ufficiale | Google | Chiave `YOUTUBE_API_KEY`. Ogni ricerca costa 100 unità su 10.000 al giorno: tetto `MAX_YT_SEARCHES` (90). Solo titoli in classifica |
| Trakt | Spettatori, visioni, liste, commenti | trakt.tv | Chiave `TRAKT_CLIENT_ID` (gratuita) |
| Rotten Tomatoes | Tomatometer, voto del pubblico, numero di recensioni | Lettura della pagina pubblica del titolo | Senza chiave. **Scraping non ufficiale**: fragile se il sito cambia. È una valutazione, non una popolarità. Solo titoli in classifica |

Dipendenza critica: la **freschezza** dell'output è quella di `fact_ga4_daily`. Il valore `max(metric_date)` è stampato a ogni esecuzione e scritto nella scheda `Leggimi`.

## 5. Output port e contratto dati

**Output.** Un file Excel in `output/best_of_trend_<start>_<end>.xlsx` (o il percorso passato con `--output`). Schede:

| Scheda | Contenuto |
| --- | --- |
| `Leggimi` | Finestra, ultimo giorno GA4 disponibile, parametri, pesi, regole di calcolo, esclusioni |
| `Sala`, `Streaming`, `Festival` | Una riga per contenuto, ordinata per trend |
| `Segnali` | Una riga per **articolo**, una colonna per fonte: Wikipedia, TMDB, IMDb, Google Trends, YouTube, Trakt, Rotten Tomatoes. Nessun indicatore composito. I valori sono dell'opera (uguali per gli articoli dello stesso titolo) e vuoti dove la fonte non ha niente. `N. fonti esterne` conta le fonti di popolarità popolate (Rotten Tomatoes è una valutazione e conta come fonte di presenza). Dove una metrica misura popolarità c'è anche uno `Score … (0-100)`: percentile dentro la sezione, calcolato solo tra i titoli che hanno quel segnale |
| `Copertura` | Per sezione e per perimetro (tutti i contenuti / solo in classifica): titoli, titoli non cercati, cercati, con ciascuna fonte, con almeno una fonte, cercati senza risultato |

**Unità di analisi.** Il *contenuto*, cioè il titolo dell'opera. Gli articoli della stessa sezione che hanno un titolo tra apici (‘…’) **all'inizio** dell'articolo si sommano. Un articolo senza titolo tra apici iniziale resta una riga a sé. Un titolo tra apici a metà frase (per esempio una rassegna "HBO Max ottobre 2026: … da ‘Peccato’ a ‘Backrooms’") non raggruppa.

**Regola "cercato".** I segnali esterni si cercano per tutti i contenuti di tutte le sezioni (anche sotto soglia e anche Festival), ma solo per quelli che sembrano un'opera: titolo tra apici, oppure articolo singolo con titolo di al massimo 45 caratteri, senza due punti e senza un anno (20xx). Gli altri (rassegne, programmi, vincitori) sono "non cercati". Wikipedia, TMDB, IMDb e Trakt vedono tutti i cercati; Google Trends, YouTube e Rotten Tomatoes solo quelli in classifica (richieste lente o a quota).

**Cosa significano "16 su 22" e simili.** Sono *titoli* (gruppi di articoli), non articoli: al denominatore i contenuti in classifica (almeno `--min-views` nostre views), al numeratore quelli con almeno una fonte esterna. La scheda `Copertura` li scompone in non cercati, cercati senza risultato e con fonte.

**Colonne delle schede di sezione** (garantite):

| Colonna | Significato |
| --- | --- |
| Pos. | Posizione nella scheda |
| Titolo, Tipi di articolo, N. articoli | Titolo, tipi presenti (Recensione, Trailer, Intervista, News), numero di articoli del gruppo |
| **Trend score** | 0–100, vuoto se non c'è nessuna fonte per Sala/Streaming |
| **Fonte score** | `Esterno (Wikipedia + TMDB)`, `Esterno (Wikipedia)`, `Esterno (TMDB)`, `Score editoriale`, `Nessun dato esterno (solo editoriale)` |
| Fase | `Novita'` (prima pubblicazione negli ultimi R giorni), `In crescita` / `In calo` (momentum ≥ 0,5 o ≤ −0,5 in log2), `Stabile` |
| Voce Wikipedia, Wiki views finestra / ultimi R gg / R gg precedenti | Abbinamento e visite |
| Momentum esterno (log2), Rank volume / momentum / TMDB | Componenti dello score |
| Voce TMDB, TMDB popolarità, TMDB popolarità R gg fa | Abbinamento, valore corrente, valore salvato almeno R giorni fa (vuoto finché non c'è storico) |
| Score editoriale | Dell'articolo migliore del gruppo |
| Nostre views finestra / ultimi R gg / R gg precedenti, Nostro momentum | Contesto: **non entrano** nello score di Sala e Streaming |
| Prima / Ultima pubblicazione, Link articolo principale | Metadati |

**Garanzie.** `Trend score` è nell'intervallo 0–100. Dentro ogni scheda i contenuti con score precedono quelli senza, poi ordine decrescente. Un articolo compare in una sola sezione.

## 6. Logica di trasformazione

1. **Finestra.** `end` = ultimo giorno GA4 nel DB (o `--end`); `start` = `end − days + 1` (default 28 giorni). La finestra è portata ad almeno `2R` giorni per poter confrontare gli ultimi R giorni con i precedenti.
2. **Articoli candidati.** Pubblicati negli ultimi `--max-age-days` (default 45) e appartenenti a una delle tre sezioni (albero ricorsivo delle categorie). Se un articolo è in più sezioni vale la priorità **Sala > Streaming > Festival**. Esclusi i titoli della lista editoriale (`EXCLUDED_TITLE_PATTERNS`).
3. **Raggruppamento per titolo.** Il primo titolo tra ‘…’ è normalizzato (minuscolo, senza accenti e punteggiatura); chiave = sezione + titolo normalizzato.
4. **Soglia.** Entrano i gruppi con almeno `--min-views` (default 30) nostre views nella finestra.
5. **Score per sezione.**

   | Sezione | Score |
   | --- | --- |
   | Festival | Score editoriale: reach 35%, engagement 35%, depth 30% (percentili con winsorizzazione 5–95), calcolato su **tutti** gli articoli del sito nella finestra. Per il gruppo, l'articolo migliore. `activeUsers` è la somma dei giornalieri (approssimazione) |
   | Sala, Streaming | Esterno: 35% volume Wikipedia, 35% momentum Wikipedia, 30% popolarità TMDB. Ognuno è un percentile (winsorizzato 5–95) *dentro la sezione*. Componente mancante = 0,5 (neutra) |

   **Volume Wikipedia** = log(1 + visite della voce nella finestra). **Momentum** = log2((visite/gg ultimi R + k) / (visite/gg R precedenti + k)), con `k` = mediana delle medie giornaliere della sezione (smorza i numeri piccoli). **TMDB** = log(1 + popolarità).
6. **Abbinamento a Wikipedia.** Ricerca su it poi en; si accetta il primo risultato il cui titolo (senza parentesi) coincide col titolo cercato, la cui descrizione breve indica film/serie/documentario e il cui **anno è noto e ≥ anno finale − 1**. Altrimenti il contenuto non ha segnale Wikipedia.
7. **Abbinamento a TMDB.** Primo risultato (film o serie) il cui titolo italiano o originale coincide e con anno di uscita ≥ anno finale − 1.
8. **Snapshot TMDB.** A ogni esecuzione la popolarità si aggiunge a `output/cache/tmdb_popularity.csv` (una riga per id e giorno). Serve a calcolare in futuro la variazione, perché TMDB non dà storico.
9. **Scrittura.** Excel con formattazione; stampa a schermo dei primi contenuti per sezione.

### Parametri

| Opzione | Default | Effetto |
| --- | --- | --- |
| `--start`, `--end` | `end` = ultimo giorno in DB | Finestra |
| `--days` | 28 | Lunghezza se manca `--start` |
| `--recent-days` | 7 | R, per momentum e fase |
| `--max-age-days` | 45 | Età massima degli articoli |
| `--min-views` | 30 | Soglia di ingresso |
| `--with-serie-tv` | off | Aggiunge le serie TV a Streaming |
| `--no-external` | off | Non chiama nessuna fonte esterna |
| `--sources` | `imdb,gt,yt,trakt,rt` | Altre fonti oltre a Wikipedia e TMDB; `""` per nessuna. Una fonte senza chiave o senza libreria è saltata con un avviso |
| `--top`, `--output` | 10, `output/…` | Righe stampate, percorso del file |

### Esecuzione

```bash
.venv/Scripts/python.exe scripts/trend_best_of.py
.venv/Scripts/python.exe scripts/trend_best_of.py --start 2026-10-05 --end 2026-11-02 --with-serie-tv
```

Prerequisiti: Postgres su (`docker compose up -d postgres`), `.env` con le variabili `POSTGRES_*`, `TMDB_API_KEY`, `YOUTUBE_API_KEY` e `TRAKT_CLIENT_ID` opzionali (senza, la fonte viene saltata con un avviso; senza TMDB salta anche IMDb), `pip install -r requirements.txt` per `pytrends`. La prima esecuzione completa richiede molti minuti (centinaia di ricerche); le successive usano la cache.

## 7. Qualità, SLO e osservabilità

| Dimensione | Obiettivo | Come si vede oggi |
| --- | --- | --- |
| Freschezza | Ultimo giorno GA4 = ieri o l'altroieri | Stampato a ogni esecuzione e nella scheda `Leggimi`. Allo stato attuale il DB si ferma al 2 novembre |
| Correttezza di calcolo | Funzioni di abbinamento e di score verificate | 14 test con risposte di rete simulate (`tests/test_external_trend.py`) |
| Correttezza degli abbinamenti | Ogni abbinamento esterno è controllabile | Colonne "Voce Wikipedia" e "Voce TMDB" in chiaro. **Non c'è un controllo automatico** |
| Copertura esterna | Quota di contenuti con almeno una fonte | Conteggio per sezione stampato a schermo. Scheda `Copertura`. Sull'ultima esecuzione (6 novembre 2026), contenuti in classifica con almeno una fonte: Sala 19/22, Streaming 8/18, Festival 53/102 |

**Non c'è ancora** un controllo automatico che blocchi l'output, per esempio se `max(metric_date)` è più vecchio di 3 giorni o se la copertura esterna crolla. È il primo punto della roadmap (§11).

## 8. Piattaforma self-service (esistente)

| Pezzo | Dove |
| --- | --- |
| Postgres e Metabase | `docker-compose.yml` |
| Schema e migrazioni | `alembic/` |
| Trasformazioni e test dati | `dbt/` |
| Orchestrazione | `make refresh`: `ingest-recent` → `ingest-ga4` → `ingest-ga4-site` → `ingest-article-scores` → `dbt-build` |
| Pianificazione | Attività Windows "TaxiDrivers ETL giornaliero", ore 07:30 (richiede il PC acceso) |
| Segreti | `.env` (ignorato da git); `.env.example` documenta i nomi |

`best_of_trend` **non** è ancora nel `make refresh`: si lancia a mano.

## 9. Governance

| Tema | Regola |
| --- | --- |
| Esclusioni editoriali | Articoli "streaming gratis" e "5 attrici…pornostar" non compaiono mai. Unica fonte: `EXCLUDED_TITLE_PATTERNS` in `midreport_client.py` |
| Dati personali | Nessuno: lavora su aggregati per articolo |
| Segreti | La chiave TMDB vive solo nel `.env`, mai nel codice, nella cache o nell'output |
| Licenze | Wikipedia: contenuti liberi, User-Agent identificativo. **TMDB**: l'uso gratuito è per progetti non commerciali e richiede di citare TMDB come fonte. **IMDb**: dataset per uso personale e non commerciale. **Google Trends** (pytrends) e **Rotten Tomatoes** (lettura della pagina): accessi non ufficiali, i termini d'uso possono vietarli; usarli per analisi interne, non ripubblicare i dati. **YouTube** e **Trakt**: API ufficiali, vanno rispettate quote e condizioni. **Da verificare sui termini** prima di far finire un dato esterno in un articolo pubblicato |
| Fonti non utilizzabili | **FlixPatrol** e **Netflix Tudum Top 10** rispondono 403 alle richieste automatiche: il blocco non va aggirato. Alternative: API a pagamento di FlixPatrol, export scaricato a mano dal sito di Netflix, o inserimento manuale |
| Cambi di metodo | Pesi, soglie, regole di abbinamento o fonti cambiano il significato dello score: vanno annotati nella versione del metodo (§11) |
| Cambi alle sorgenti | Se cambia la mappa delle categorie (`wp_client/posts-service.js`) vanno riviste le radici in `SECTION_ROOTS` |

## 10. Cuciture per un eventuale mesh

Dove si spezzerebbe il prodotto se arrivassero più team o più consumatori:

| Prodotto | Tipo | Oggi | Contratto già presente |
| --- | --- | --- | --- |
| Articoli e categorie WordPress | Source-aligned | `articles_dim`, `categories_dim`, `articles_categories` | Migrazioni Alembic |
| Traffico GA4 per articolo | Source-aligned | `fact_ga4_daily` | Migrazioni, test dbt |
| Score editoriale per periodo | Aggregato | `fact_article_score_period`, versione `balanced-v2` | Migrazione 0005, `METHOD_VERSION` |
| Attenzione esterna per titolo (Wikipedia, TMDB, IMDb, Trends, YouTube, Trakt, RT) | Source-aligned (esterno) | `external_trend.py`, `signal_sources.py` e cache in `output/cache/` | Nessuno: è la cucitura più debole |
| **Best of Trend** | Consumer-aligned | Questo documento | §5 |

La candidata naturale a diventare un prodotto a sé è l'attenzione esterna per titolo (con tabella in Postgres e storico), perché oggi TMDB non ne ha e va accumulato.

## 11. Limiti noti e roadmap

**Limiti.**

- **Abbinamento per titolo.** Due opere con lo stesso titolo nella stessa sezione si fondono; un titolo ambiguo può agganciare la voce sbagliata. Visto sul campo: "La bambola" agganciato a una serie TV 2026 su TMDB.
- **Opere vecchie escluse.** Il filtro sull'anno scarta anche le riedizioni di classici (es. "Matrix", "I diavoli").
- **Rassegne mensili di streaming.** Non sono opere: non hanno segnale esterno e restano in coda.
- **Streaming.** Pochi titoli in classifica hanno un dato esterno (vedi `Copertura`), quindi i percentili sono instabili: ordine di massima.
- **Google Trends.** I valori sono relativi al termine ancora nella stessa richiesta e arrotondati a interi: i titoli molto piccoli risultano 0. I titoli ambigui (es. "Animals") mescolano significati diversi.
- **YouTube.** Il trailer è scelto dal primo risultato con titolo e "trailer" nel nome; può essere il video sbagliato o di un canale non ufficiale.
- **Rotten Tomatoes.** Per le serie la pagina è quella della prima stagione.
- **Variazioni nel tempo.** Voti IMDb, views YouTube e spettatori Trakt sono cumulativi e senza storico: la variazione compare solo dopo qualche esecuzione (`snapshots.csv`).
- **TMDB.** Popolarità globale e senza storico (la variazione si ottiene solo dopo qualche giorno di snapshot).
- **Score editoriale per Festival.** Somma di `active_users` giornalieri, non utenti unici di periodo; con 30–100 views premia l'engagement più dei volumi.
- **Il titolo tra apici** è una convenzione redazionale: gli articoli che non la rispettano non si raggruppano.

**Roadmap** (in ordine di valore).

1. **Controlli automatici**: blocco se i dati GA4 sono più vecchi di 3 giorni; allerta se la copertura esterna scende sotto una soglia.
2. **`METHOD_VERSION`** nel codice (`best-of-trend-v1`), scritta nella scheda `Leggimi`, da incrementare a ogni cambio di pesi o regole.
3. **Tabella di conferma degli abbinamenti**: un CSV `titolo → voce Wikipedia / id TMDB` che l'utente può correggere a mano e che ha la precedenza sulla ricerca automatica.
4. **Persistenza in Postgres** dell'output (tabella per finestra e versione del metodo) accanto all'Excel, per confronti nel tempo e per Metabase.
5. **Aggiunta a `make refresh`**, con finestra e flag di default.
6. **`fact_article_signal` (fatta, migrazione 0006)**: segnali in formato lungo (articolo, fonte, metrica, data di rilevazione, finestra, versione `signals-v1`), scritti a ogni esecuzione in modo idempotente (`--no-save-db` per saltare). Il valore è dell'opera e si ripete per ogni suo articolo. Da fare: usarla come unica fonte dello storico al posto di `snapshots.csv` e di `tmdb_popularity.csv`, e leggere l'Excel da lì.
7. **Top 10 streaming** per l'Italia: FlixPatrol (API a pagamento) o export Netflix scaricato a mano, perché l'accesso automatico è bloccato (§9).
8. **Documentazione complessiva** dell'infrastruttura dati di Taxi Drivers Lab (WordPress, GA4, Postgres, dbt, Metabase, scheduling), che questo documento richiama.
