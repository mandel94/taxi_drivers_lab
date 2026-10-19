# Guida back-end · Contenuti e Panoramica

Percorso a passi per costruire a mano il livello dati dei tab **Contenuti** (release 1) e **Panoramica** e **Acquisizione** (release 2), seguendo il blueprint del 15 ottobre 2026.

**Come lavoriamo.** Io faccio l'analytics engineer, tu scrivi il codice. Ogni passo ha lo stesso formato: *Perché* (il concetto), *Fai tu* (cosa costruire), *Checkpoint* (come sai che è giusto). Ti do codice completo solo dove c'è una trappola, altrimenti uno scheletro. Se un checkpoint non torna, fermati e incollami l'output: non andare avanti sperando.

**Stato al 19 ottobre 2026, sera.** Il livello dati delle release 1 e 2 è costruito e gira sul tuo DB di lavoro. Il codice l'ho scritto io su tua richiesta: i passi qui sotto restano come spiegazione del *perché* è fatto così e come si verifica. Leggi i file prima di fidarti.

| Pezzo | Dove | Stato |
| --- | --- | --- |
| Migration 0004 (sito, canale, periodo, log) | `alembic/versions/0004_ga4_site_tables.py` | Applicata |
| Ingestione sito, canali, periodi | `ga4_client/ingest_ga4_site.py` | Funzionante contro GA4 vero |
| Backfill dinamico (`--auto`) e log | `ga4_client/backfill_plan.py`, `etl_log.py`, `ingest_ga4.py` | Funzionante, provato con un fermo simulato |
| Progetto dbt (22 modelli, 3 seed, 52 test) | `dbt/` | `dbt build` 77 su 77 verdi |
| Mart | schema `marts` | Costruiti: contenuti, panoramica, acquisizione, salute dei dati |
| ETL giornaliero | `make refresh`, `scripts/run_refresh.cmd`, attività Windows "TaxiDrivers ETL giornaliero" | Pianificato alle 07:30, prima esecuzione il 20 ottobre |
| Test | `tests/test_ga4_site_tables.py` (9), `tests/test_backfill_plan.py` (11) | Tutti superati |

Backfill: sito, canali e periodi da agosto 2025; dati per articolo dal 16 agosto 2026 (il backfill degli articoli precedente non è richiesto per ora, quindi il confronto con l'anno prima a livello articolo e sezione sarà `null` fino ad agosto 2027). Il funzionamento quotidiano è descritto in [etl_giornaliero.md](etl_giornaliero.md). Per rilanciare i test: `.venv/Scripts/python.exe tests/test_ga4_site_tables.py` e `tests/test_backfill_plan.py`.

**Scelte fatte durante la costruzione**, da conoscere perché si discostano dal blueprint o lo precisano:

| Scelta | Perché |
| --- | --- |
| Tolleranza riconciliazione canali: 5% al giorno, 1% sulla settimana | Sui dati reali lo scarto giornaliero tra canali e sito oscilla (massimo 3,45%, media vicina a zero): con l'1% al giorno fallirebbe il 10% dei giorni. Sulla settimana lo scarto si compensa e l'1% regge |
| `dim_section` ha una quattordicesima riga, `non_classificato` | Gli articoli senza categoria mappata (644, l'1,2%) devono comparire nei totali per sezione, altrimenti le quote non sommano a 1 |
| L'elenco dei canali di `mart_channel_daily` viene dai dati, non dal seed | Un gruppo nuovo di GA4 non va perso e la somma dei canali continua a tornare col sito; il seed `dim_channel` dà solo etichette |
| Le finestre di copertura sono variabili, non `min(data)` | Nel DB ci sono 3 giorni isolati caricati per prova: `min(data)` avrebbe creato una spine con mesi di zeri finti. Il Makefile le definisce una volta (`GA4_ARTICLES_START`, `GA4_SITE_START`) e le passa a ETL e dbt |
| Il refresh non si ferma al primo errore | Un problema di WordPress non deve bloccare GA4 e viceversa. Il codice di uscita è non zero se qualcosa è fallito e `mart_data_health` lo segnala |
| `ingest_ga4.py` ora esce con codice 1 se un giorno fallisce | Prima restituiva sempre 0 e un errore passava inosservato |

La parte grafica sta in un documento separato: [brief_frontend_contenuti_panoramica.md](brief_frontend_contenuti_panoramica.md). Quel documento descrive i mart come un contratto, quindi chi fa il layout può partire da subito.

---

## 0. Dove siamo davvero

Ho lanciato la query di copertura del blueprint sul DB locale (15 ottobre 2026). Tre risultati cambiano il piano.

| Cosa | Risultato | Conseguenza |
| --- | --- | --- |
| `fact_ga4_daily` | 218.216 righe, 11.096 articoli, **dal 16/08 al 14/09/2026** (30 giorni, nessun buco), ultimo caricamento 15/09 | Manca un mese fino a oggi e non c'è storico per il confronto con l'anno prima |
| `articles_dim` | 54.845 articoli, ultimo pubblicato il 15/09/2026 | Va riallineata prima di rilanciare GA4, altrimenti gli articoli nuovi non si agganciano |
| `fact_wp_engagement_weekly` | **0 righe**, e nessuno script la popola (`ingest-articles.js` lo dichiara nell'intestazione) | `comment_count` e `was_modified_in_week` escono dalla fase 1 |
| `fact_ga4_daily_legacy_pagepath` | 0 righe | Nessuno storico nascosto da recuperare |
| **Canali GA4** (Organic Search, Direct...) | **Assenti.** Nessuna tabella o colonna, nessuna chiamata a GA4 con la dimensione canale (verificato su DB, `ga4_client/`, `wp_client/`, migration e Makefile). Schema fermo alla migration 0003 | Entrano nella release 2 con `fact_ga4_channel_daily` e `mart_channel_daily` |
| Makefile | `ingest-recent` è nell'help ma **non ha ricetta**. Mancano `ingest-ga4-site`, `dbt-build` e `refresh`. Il default di `ingest-ga4` ricarica 30 giorni a ogni esecuzione | Vanno scritti (passi 1, 8 e 10) |
| `categories_dim` | 271 categorie, tutte `wp_taxonomy = 'category'` | Lo script non ha mai letto tassonomie custom: il punto aperto 5 resta aperto lato WordPress |
| `articles_categories` | 63.563 legami per 54.845 articoli (circa 1,16 categorie ad articolo) | Pochi articoli stanno in più categorie, quindi la regola della sezione primaria ne toccherà pochi |

Altri numeri che ci servono dopo: nei 30 giorni caricati le visualizzazioni sono 62.138 e i secondi di coinvolgimento 1.760.937. 1.331 articoli su 54.845 cambiano giorno di pubblicazione se converti il fuso in `Europe/Rome`. 151 coppie articolo-giorno in GA4 sono precedenti alla pubblicazione (anteprime o fuso). Tutte le 25 categorie citate in `CATEGORIES` esistono in `categories_dim`. Il Festival di Cinema ha 166 categorie sotto di sé.

### Dove il blueprint e la realtà non coincidono

Sono sette punti. Te li dico subito perché è la parte che separa chi segue il documento da chi lo capisce.

1. **Non densificare i mart per articolo.** Il blueprint dice che ogni mart parte da `dim_date` e unisce a sinistra. Per i mart di sito e di sezione va benissimo (poche righe). Per gli articoli sarebbe 54.845 articoli per ogni giorno: decine di milioni di righe di zeri. I mart per articolo restano **sparsi**: l'assenza di riga vale zero.
2. **Un confronto in una tabella piatta funziona solo con spostamento fisso.** `_prev` come "periodo precedente di pari lunghezza" dipende dall'intervallo scelto dall'utente, che la tabella non conosce. Valgono solo `_py` (364 giorni o 52 settimane prima), `_p7` (7 giorni prima, nei mart giornalieri) e `_prev` nei mart dove l'unità è la settimana o il mese (una settimana o un mese prima). Il motivo è nel passo 7.
3. **Servono due seed per le sezioni, non uno.** Nel codice `includeChildren` è una proprietà della *categoria*, non della sezione. Il blueprint lo mette in `dim_section`, ma una sezione come "Serie TV" ha sette categorie con valori diversi.
4. **L'aggancio articolo-pagina non passa da `url_path`.** Il codice (`ga4_service.py`, `resolve_page_path`) usa il prefisso numerico del permalink (`/<article_id>/<categoria>/<slug>.html`) e solo in fallback lo slug. `url_path` resta utile come colonna informativa e per il test di unicità, ma non è la chiave di aggancio.
5. **`mart_data_health` deve essere una vista.** Se lo costruisci come tabella, quando tutta la pipeline si ferma il riquadro continua a dire "ok" perché non viene più ricostruito. Una vista valuta `now()` a ogni lettura.
6. **I canali entrano nella release 2.** `fact_ga4_channel_daily` non esiste e nessuna parte della pipeline li raccoglie. Li aggiungiamo insieme alle tabelle di Panoramica: stessa migration (0004), stesso script di ingestione, stesso `refresh`. Hanno due particolarità che le altre fact non hanno: il caricamento è "cancella e reinserisci" invece del solo upsert, e `active_users` per canale non si somma (passi 8 e 9).
7. **La pipeline di aggiornamento ha dei buchi.** `ingest-recent` non ha ricetta nel Makefile (lo script supporta già `INCREMENTAL=1`), mancano i target per sito, canali e dbt, e il default di `ingest-ga4` è 30 giorni a ogni esecuzione, cioè 30 chiamate a GA4. Per l'aggiornamento giornaliero il blueprint prevede 3 giorni.

---

## Mappa dei passi

| Release | Passo | Cosa | Output |
| --- | --- | --- | --- |
| Prima di tutto | 0 | Igiene: credenziali e backup | `.gitignore`, file `.sql` in `backups/` |
| | 1 | Riallineare articoli e GA4, backfill | fact GA4 fino a ieri, storico lungo |
| **1 · Contenuti** | 2 | Installare dbt | `dbt debug` verde |
| | 3 | Seed sezioni | `dim_section`, `section_category_map` |
| | 4 | Staging | 4 modelli `stg_*` |
| | 5 | `dim_date`, `dim_article` | dimensioni conformi |
| | 6 | Intermediate e mart Contenuti | 5 mart + test |
| **2 · Panoramica e Acquisizione** | 7 | Migration 0004 | 4 tabelle raw nuove (sito, canale, periodo, log) |
| | 8 | `ingest_ga4_site.py` | totali di sito, canali e utenti per periodo |
| | 9 | Seed canali e mart | `mart_site_daily`, `mart_site_period`, `mart_channel_daily` |
| Chiusura | 10 | Orchestrazione e controlli | `make refresh`, alert |

La release 1 non dipende dalle tabelle di sito: puoi consegnare Contenuti al front-end prima di toccare la migration.

---

## Passo 0 · Igiene (10 minuti)

**Perché.** In `ga4_client/` ci sono `client_secrets.json` e `token.json`: il secondo è un token OAuth con accesso in lettura alla tua property GA4. Il `.gitignore` oggi non li copre. E il blueprint stesso ricorda che `make clean` fa `down -v`: prima di ricaricare mesi di storico GA4 si fa un backup.

**Fai tu.**
1. Aggiungi a `.gitignore`: `ga4_client/client_secrets.json`, `ga4_client/token.json`, `backups/`.
2. Crea la cartella `backups/` e fai un dump da Git Bash:

```bash
mkdir -p backups
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/td_$(date +%Y%m%d).sql
```

**Checkpoint.** Il file pesa più di qualche MB e `grep -c "CREATE TABLE" backups/td_*.sql` restituisce almeno 6.

---

## Passo 1 · Riallineare i dati e fare il backfill

**Perché.** Un dashboard su dati fermi al 14 settembre non si può nemmeno guardare. E il confronto con l'anno prima richiede almeno 13 mesi: 364 giorni di spostamento più la finestra che vuoi visualizzare.

**Fai tu.** Prima gli articoli, poi GA4 (lo script ti avvisa degli id GA4 che non trova in `articles_dim`).

**Il Makefile ora ha la ricetta** (aggiunta il 19 ottobre): `ingest-recent` era già in `.PHONY` e nell'help ma non aveva un corpo. Quella che trovi nel Makefile è questa, copia di `ingest` con `INCREMENTAL=1` (e con il **tab** a inizio riga, che nei Makefile è obbligatorio):

```make
ingest-recent: check-env up wait-db migrate
	cd wp_client && DATABASE_URL=$(DATABASE_URL) INCREMENTAL=1 MAX_PAGES=$(MAX_PAGES) /ucrt64/bin/node ingest-articles.js
```

Perché così: `ingest-articles.js` ha già la modalità incrementale (variabile `INCREMENTAL`), quindi non serve scrivere altro codice. Poi:

```bash
make ingest-recent
make ingest-ga4 GA4_ARGS="--start 2026-09-15 --end yesterday"
```

Prima del backfill lungo fai un test sul punto aperto 3 (profondità storica): chiedi **un solo giorno** molto indietro.

```bash
make ingest-ga4 GA4_ARGS="--date 2025-08-14"
```

Se GA4 risponde con righe, procedi a blocchi di circa 60 giorni all'indietro (`--start`/`--end`). Lo script scrive un commit per giorno e ogni upsert è idempotente, quindi puoi interromperlo e riprendere.

**Trappola.** `_RETRYABLE_EXCEPTIONS` in `ga4_client.py` ritenta solo timeout e servizio non disponibile. Un errore di quota esaurita non viene ritentato e il giorno viene saltato (lo vedi in coda al log come "ERRORE"). Se succede, fermati, aspetta il reset giornaliero della quota e rilancia lo stesso blocco.

**Checkpoint.** Query dei giorni mancanti (esegui in psql o nell'editor SQL di Metabase). Deve restituire zero righe:

```sql
SELECT d::date AS giorno_mancante
FROM generate_series(
       (SELECT min(metric_date) FROM fact_ga4_daily),
       (SELECT max(metric_date) FROM fact_ga4_daily),
       interval '1 day') d
WHERE d::date NOT IN (SELECT DISTINCT metric_date FROM fact_ga4_daily);
```

E `max(metric_date)` deve essere ieri. Scrivi in un appunto il primo giorno recuperato: sarà la data di inizio di `dim_date`.

---

## Passo 2 · Installare dbt (45 minuti)

**Perché.** dbt trasforma il raw in mart con file SQL versionati. Ogni modello è un `SELECT`: dbt si occupa di creare la vista o la tabella, di ordinare le dipendenze e di eseguire i test.

**Fai tu.**
1. Nel `.venv` esistente: `pip install dbt-postgres`. Poi `pip freeze | grep -i dbt` e copia le versioni in `requirements.txt`.
2. Crea la cartella `dbt/` con questa struttura:

```
dbt/
├── dbt_project.yml
├── profiles.yml
├── packages.yml
├── macros/generate_schema_name.sql
├── models/{staging,intermediate,marts}/
├── seeds/
└── tests/
```

3. `profiles.yml`: host `localhost`, porta da `env_var('POSTGRES_PORT')` (nel compose è 5434), utente, password e database sempre da `env_var(...)`. Mai password in chiaro nel file.
4. In `dbt_project.yml` configura le materializzazioni: `staging` e `intermediate` come `view`, `marts` come `table`, con `+schema` uguale al nome della cartella. Aggiungi `vars: { date_start: '2025-01-01' }` (usa la data del passo 1).
5. Crea la macro che serve a evitare gli schemi `public_staging`:

```sql
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}{{ target.schema }}
    {%- else -%}{{ custom_schema_name | trim }}{%- endif -%}
{%- endmacro %}
```

**Trappola.** Senza quella macro dbt concatena lo schema di default e quello personalizzato: otterresti `public_marts` invece di `marts`, e il front-end cercherebbe uno schema che non esiste.

6. `packages.yml` con `dbt-labs/dbt_utils` (prendi la versione compatibile con la tua dbt-core da hub.getdbt.com) e poi `dbt deps`.

**Checkpoint.** Da `dbt/`: `dbt debug --profiles-dir .` tutto verde.

---

## Passo 3 · Seed delle sezioni

**Perché.** Oggi la regola "quale categoria appartiene a quale sezione" vive nel codice JavaScript (`wp_client/posts-service.js`, righe 30-68). Spostarla in un CSV la rende leggibile dalla redazione e modificabile senza toccare codice.

**Fai tu.** Due file in `dbt/seeds/`.

`dim_section.csv`: `section_key,section_name,priority`. Sono 13 sezioni, le stesse chiavi di `CATEGORIES`. `section_key` è lo slug minuscolo senza accenti (`serie_tv`, `festival_di_cinema`...).

`section_category_map.csv`: `section_key,category_id,include_children`. Una riga per ogni `{ id, includeChildren }` del codice: sono 25 righe. Copiale a mano, con i commenti di slug come controllo.

Esempio delle prime righe:

```
section_key,category_id,include_children
news,32998,true
news,32989,true
recensioni,218,true
```

Per `priority` ti propongo un ordine **provvisorio** (dal più specifico al più generico) per sbloccarti. È una scelta editoriale: va validata con la redazione e cambia il risultato di tutti i grafici per sezione.

| Priorità | Sezione | Priorità | Sezione |
| --- | --- | --- | --- |
| 1 | Interviste | 8 | In Sala |
| 2 | Live Streaming On Demand | 9 | Recensioni |
| 3 | Trailers | 10 | Guide e Film da Vedere |
| 4 | Festival di Cinema | 11 | Speciali e Magazine |
| 5 | Serie TV | 12 | Rubriche |
| 6 | Animazione | 13 | News |
| 7 | Cult Movies | | |

In `dbt_project.yml` forza i tipi con `seeds: +column_types` (`category_id: integer`, `include_children: boolean`, `priority: integer`). Senza, dbt li deduce dal contenuto e un `true`/`false` può diventare testo.

**Checkpoint.** `dbt seed` carica 13 e 25 righe. Più avanti il test `relationships` verso `categories_dim` ti dirà se hai sbagliato un id (io ho già verificato che tutti e 25 esistono).

---

## Passo 4 · Staging

**Perché.** Lo staging è lo strato "pulizia, nessuna logica": nomi coerenti, tipi giusti, un modello per tabella raw. Se domani cambia la tabella raw, correggi solo qui.

**Fai tu.** Prima dichiara le tabelle raw in `models/staging/_sources.yml` (source `public`: `articles_dim`, `categories_dim`, `articles_categories`, `fact_ga4_daily`). Poi quattro modelli:

| Modello | Cosa fa |
| --- | --- |
| `stg_articles` | Solo `status = 'publish'`. Aggiunge `published_date` convertita in fuso Roma. Non porta `content_html` oltre `word_count` |
| `stg_categories` | `category_id`, `parent_id`, `name`, `slug` |
| `stg_article_categories` | Il ponte, così com'è |
| `stg_ga4_article_daily` | La fact long portata in formato largo: una riga per articolo e giorno |

Il pivot è il pezzo da capire. La PK di `fact_ga4_daily` garantisce una sola riga per (articolo, giorno, metrica), quindi `sum` con `filter` equivale a "prendi quel valore":

```sql
select
    article_id,
    metric_date as date_day,
    sum(metric_value) filter (where metric_name = 'screen_page_views')     as views,
    sum(metric_value) filter (where metric_name = 'user_engagement_duration') as engagement_seconds,
    sum(metric_value) filter (where metric_name = 'sessions')              as sessions_attributed,
    sum(metric_value) filter (where metric_name = 'engaged_sessions')      as engaged_sessions_attributed
from {{ source('public', 'fact_ga4_daily') }}
group by 1, 2
```

Non pivotare `engagement_rate`, `bounce_rate` e `average_session_duration`: sono rapporti già calcolati da GA4 e la regola del blueprint è ricalcolarli dai componenti.

La conversione di fuso in `stg_articles`:

```sql
(published_at at time zone 'Europe/Rome')::date as published_date
```

**Trappola.** Il tuo server Postgres lavora in UTC. `published_at::date` darebbe il giorno sbagliato per un articolo uscito dopo le 22 UTC (le 00:xx a Roma): sono i 1.331 articoli che ho contato.

**Checkpoint.** `dbt run -s staging` e poi confronta: `count(*)` di `stg_ga4_article_daily` deve essere **27.277** (le coppie distinte articolo-giorno) con 62.138 visualizzazioni totali, se non hai ancora fatto il backfill. Dopo il backfill i numeri crescono: l'importante è che righe e coppie distinte nella fact coincidano.

---

## Passo 5 · `dim_date` e `dim_article`

**`dim_date`.** Una riga per giorno. Tre campi servono davvero: `date_day`, `week_start_date` (il lunedì) e `month_start`. Postgres ha già la funzione giusta: `date_trunc('week', d)` restituisce il lunedì (ho controllato: per il 15 ottobre 2026 dà il 12). Scheletro:

```sql
select
    d::date                              as date_day,
    date_trunc('week',  d)::date         as week_start_date,
    date_trunc('month', d)::date         as month_start,
    extract(isoyear from d)::int         as iso_year,
    extract(week    from d)::int         as iso_week,
    extract(isodow  from d) in (6, 7)    as is_weekend
from generate_series('{{ var("date_start") }}'::date,
                     date_trunc('year', current_date) + interval '2 years' - interval '1 day',
                     interval '1 day') d
```

Aggiungi tu `quarter`. Il test dbt è `unique` e `not_null` su `date_day`.

**Le sezioni degli articoli.** Qui c'è la parte più istruttiva. Serve espandere ogni voce di `section_category_map` ai suoi discendenti quando `include_children` è vero. In SQL si fa con una query ricorsiva (modello `int_section_categories`):

```sql
with recursive tree as (
    select m.section_key, c.category_id, m.include_children
    from {{ ref('section_category_map') }} m
    join {{ ref('stg_categories') }} c on c.category_id = m.category_id
  union
    select t.section_key, c.category_id, t.include_children
    from tree t
    join {{ ref('stg_categories') }} c on c.parent_id = t.category_id
    where t.include_children
)
select distinct section_key, category_id from tree
```

Ho provato la stessa struttura sul DB: partendo dalla categoria 20 (Festival) escono 166 categorie.

**Perché `union` e non `union all`.** Il `union` elimina i duplicati, quindi se per un errore di dati due categorie si puntassero a vicenda la ricorsione si fermerebbe da sola invece di girare all'infinito.

Poi `int_article_section`: unisci `stg_article_categories` a `int_section_categories` e a `dim_section`, tieni (articolo, sezione) distinti e marca la primaria:

```sql
row_number() over (partition by article_id order by priority, section_key) = 1 as is_primary
```

Gli articoli senza nessuna sezione mappata vanno in `non_classificato`: usa `coalesce`, non scartarli.

**`dim_article`** (nello schema `marts`): `article_id`, `slug`, `title`, `link`, `url_path` (il `link` senza dominio, minuscolo), `published_date`, `primary_section_key`, `word_count`. Stima le parole togliendo i tag:

```sql
array_length(regexp_split_to_array(
    trim(regexp_replace(content_html, '<[^>]+>', ' ', 'g')), '\s+'), 1) as word_count
```

Sul campione risulta una media di circa 639 parole e una sola riga vuota (gestisci il `null`). Non esporre `content_html`, `excerpt`, `author_*`.

**Checkpoint.** Tre domande a cui devi saper rispondere con una query: quanti articoli sono in `non_classificato` (in percentuale), che nessun `article_id` compare due volte in `dim_article`, e che `primary_section_key` esiste sempre in `dim_section`. Gli ultimi due sono test dbt (`unique`, `relationships`).

---

## Passo 6 · Intermediate e mart di Contenuti

**`int_article_daily`** (sparso). Parte da `stg_ga4_article_daily` e fa un `inner join` con `dim_article`, quindi tiene solo gli articoli pubblicati. Aggiunge tre campi:

- `age_days = greatest(0, date_day - published_date)`. Il `greatest` serve: 151 righe hanno una data precedente alla pubblicazione (anteprime del redattore, o fuso) e un'età negativa romperebbe le fasce.
- `age_bucket` con un `case`: `0-7`, `8-30`, `31-90`, `91-365`, `366+`. Si calcola alla data della metrica, non a oggi, perché altrimenti lo stesso articolo cambierebbe fascia ogni giorno e i confronti tra periodi non sarebbero stabili.
- `is_new_30d = age_days < 30`.

**I cinque mart.** Costruiscili in quest'ordine, ognuno parte dal precedente:

| Mart | Densità | Cosa devi sapere |
| --- | --- | --- |
| `mart_article_daily` | sparso | Colonne in [brief front-end](brief_frontend_contenuti_panoramica.md). `is_provisional = date_day >= current_date - 2` |
| `mart_article_weekly` | sparso | Somme per (articolo, lunedì) più `active_days`. `weeks_since_publication` dal lunedì della pubblicazione |
| `mart_section_weekly` | denso | Spine: settimane × 13 sezioni |
| `mart_content_weekly` | denso | Una riga per settimana |
| `mart_data_health` | vista | Vedi sotto |

**Il punto delicato è `mart_section_weekly`.** La spine (l'elenco di tutte le combinazioni settimana-sezione) deve coprire **solo l'intervallo dove abbiamo dati**, cioè da `date_trunc('week', min(date_day))` a `date_trunc('week', max(date_day))` della fact. Poi:

- `views_share = views / nullif(sum(views) over (partition by week_start_date), 0)`. È la quota sul totale delle visualizzazioni attribuite agli articoli, non sul sito: così le quote sommano a 100%.
- `_prev = lag(views, 1) over (partition by section_key order by week_start_date)` e `_py = lag(views, 52) over (...)`.
- `is_complete_week`: vero se il lunedì è ≥ al primo giorno coperto e la domenica è ≤ all'ultimo giorno coperto meno 2.

**Perché la spine deve essere densa.** `lag(52)` vale "un anno fa" solo se non mancano settimane nella tabella. E deve fermarsi all'intervallo coperto, altrimenti le settimane prima del 16 agosto 2026 comparirebbero con zeri veri e il confronto mostrerebbe un crollo falso invece di un `null`. Dove manca lo storico, `_py` resta `null`: "non disponibile" non è "zero".

**Trappola della prima settimana.** Se i dati partono a metà settimana, quella settimana ha meno giorni delle altre: per questo esiste `is_complete_week`.

**`mart_content_weekly`.** Per ogni settimana: `views_total`, `views_new_30d` (somma sugli articoli con `is_new_30d`), `views_archive` (il resto), `share_new`, `top10_share` (visualizzazioni dei 10 articoli più letti diviso totale: calcola una `row_number()` per settimana sugli articoli), `articles_active` (articoli con almeno una visualizzazione). Stessi `_prev` e `_py`.

**`mart_data_health`.** Configuralo con `{{ config(materialized='view') }}`. Una riga per fonte (`ga4_articles`, `wp_articles`) con `last_loaded_at` (da `max(fetched_at)` e `max(ingested_at)`), `last_covered_date`, `days_missing_last_30` (stessa logica della query del passo 1) e `status`:

- `error` se l'ultimo caricamento è più vecchio di 72 ore, `warn` se più di 36 ore, altrimenti `ok`.
- In release 2 aggiungerai `matching_coverage` e le righe per `ga4_site_daily`, `ga4_channel_daily` e `ga4_site_period` (leggono `etl_run_log` e le `fetched_at` delle nuove fact). Per ora lascia `matching_coverage` a `null`.

**Checkpoint.** Scrivi un test singolare in `dbt/tests/` che confronti, per un giorno qualsiasi, la somma delle visualizzazioni in `mart_article_daily` con quella in `fact_ga4_daily`. La differenza deve stare nelle sole righe di articoli non pubblicati (dovrebbe essere vicina a zero). Poi: `dbt build` tutto verde e i cinque mart visibili in Metabase dopo "Sync database schema now".

**Consegna al front-end.** Avvisami quando il `dbt build` è verde: da quel momento chi fa il layout può collegare le carte di Contenuti ai dati veri.

---

## Passo 7 · Migration 0004 (release 2)

**Perché.** Le fact GA4 per articolo non possono dare i totali del sito (la misura è attribuita a ogni pagina visitata). Servono tabelle dove GA4 ci dà il totale direttamente.

**Fai tu.** `alembic revision -m "ga4 site tables"`, poi rinomina il file e imposta `revision = "0004_ga4_site_tables"` e `down_revision = "0003_fact_ga4_daily_long_format"`, come le migration precedenti. Scrivi SQL puro con `op.execute()` e aggiungi i `COMMENT ON TABLE` come nelle migration 0001-0003.

Quattro tabelle. La prima per intero, le altre per differenze:

```sql
CREATE TABLE fact_ga4_site_daily (
    metric_date              DATE PRIMARY KEY,
    active_users             INTEGER NOT NULL DEFAULT 0 CHECK (active_users >= 0),
    new_users                INTEGER NOT NULL DEFAULT 0 CHECK (new_users >= 0),
    sessions                 INTEGER NOT NULL DEFAULT 0 CHECK (sessions >= 0),
    engaged_sessions         INTEGER NOT NULL DEFAULT 0 CHECK (engaged_sessions >= 0),
    screen_page_views        INTEGER NOT NULL DEFAULT 0 CHECK (screen_page_views >= 0),
    user_engagement_duration NUMERIC(14,2) NOT NULL DEFAULT 0,
    fetched_at               TIMESTAMPTZ NOT NULL DEFAULT now()
)
```

| Tabella | Differenze rispetto a quella sopra |
| --- | --- |
| `fact_ga4_site_period` | PK `(period_type, period_start)`. `period_type TEXT CHECK (period_type IN ('week','month'))`, `period_end DATE NOT NULL`, `is_complete BOOLEAN NOT NULL`. Solo `active_users` e `new_users`. `CHECK (period_end >= period_start)` |
| `fact_ga4_channel_daily` | PK `(metric_date, channel_group)`. `channel_group TEXT NOT NULL` **senza CHECK** sui valori: GA4 può aggiungere gruppi e il caricamento non deve fallire (un test dbt con severità `warn` segnalerà i valori nuovi). Stesse sei colonne di metriche e stesso `fetched_at`. Indice su `channel_group` |
| `etl_run_log` | `run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY`, `source TEXT NOT NULL`, `started_at TIMESTAMPTZ NOT NULL DEFAULT now()`, `finished_at`, `date_from`, `date_to`, `rows_written INTEGER`, `status TEXT CHECK (status IN ('running','success','failed'))`, `error_message TEXT` |

**Perché i vincoli sono pochi.** Nel raw mettiamo solo ciò che non può essere vero in nessun caso (conteggi negativi). Le regole di dominio, come "le sessioni coinvolte non superano le sessioni", vanno in `dbt test` con severità `warn`: se GA4 rivede un dato, il caricamento non deve fallire a metà.

Nel `COMMENT` di `fact_ga4_channel_daily` scrivi due cose: quale dimensione GA4 usi per il canale (vedi passo 8) e che `active_users` **non si somma tra canali**, perché la stessa persona può comparire in più gruppi.

`downgrade()` droppa le quattro tabelle in ordine inverso. Poi `make migrate` e `make db_docs`.

**Checkpoint.** `alembic current` mostra `0004_ga4_site_tables` e `alembic downgrade -1` seguito da `alembic upgrade head` gira senza errori.

---

## Passo 8 · `ga4_client/ingest_ga4_site.py`

**Perché.** Non serve un secondo client: `GA4Client.run_query` accetta già metriche e dimensioni a piacere.

**Fai tu.** Un nuovo script, nello stile di `ingest_ga4.py` (argparse, `GA4_PROPERTY_ID` e `DATABASE_URL` dall'ambiente), con tre funzioni:

**`ingest_site_daily(start, end)`**: una sola chiamata `run_query` con `dimensions=["date"]` e le metriche `activeUsers, newUsers, sessions, engagedSessions, screenPageViews, userEngagementDuration`. Una query per l'intero intervallo, non una per giorno: il vincolo "una query per giorno" dello script articoli serve a evitare che `pagePath` faccia esplodere le righe, mentre qui sono al massimo 400 righe. Poi upsert con `execute_values`:

```sql
INSERT INTO fact_ga4_site_daily (metric_date, active_users, new_users, sessions,
                                 engaged_sessions, screen_page_views, user_engagement_duration)
VALUES %s
ON CONFLICT (metric_date) DO UPDATE SET
    active_users = EXCLUDED.active_users, new_users = EXCLUDED.new_users,
    sessions = EXCLUDED.sessions, engaged_sessions = EXCLUDED.engaged_sessions,
    screen_page_views = EXCLUDED.screen_page_views,
    user_engagement_duration = EXCLUDED.user_engagement_duration,
    fetched_at = now()
```

**`ingest_channel_daily(start, end)`**: una sola chiamata `run_query` con `dimensions=["date", "sessionDefaultChannelGroup"]` e le stesse sei metriche del sito. Sono circa 10 righe al giorno, quindi anche 400 giorni stanno sotto le 5.000 righe e una query basta. Prima di scrivere il codice verifica con `getMetadata` (o nell'esploratore delle dimensioni di GA4) che il nome esista nella tua property: c'è anche `sessionPrimaryChannelGroup`, la variante più recente. Scegline **una** e annotala nel `COMMENT` della tabella: cambiarla dopo il backfill spezza lo storico.

**Trappola: per i canali l'upsert non basta.** Se GA4 rivede un giorno e un gruppo sparisce o cambia nome (ad esempio una riga `Unassigned` che viene riclassificata), l'upsert aggiorna le righe che tornano ma lascia quelle vecchie, e la somma dei canali non torna più col totale del sito. Per questa tabella scrivi in una sola transazione: prima `DELETE FROM fact_ga4_channel_daily WHERE metric_date BETWEEN %s AND %s`, poi l'insert con `execute_values`. Così ogni giorno è sempre la fotografia dell'ultima risposta di GA4. Il commit è uno solo: se l'insert fallisce, il `DELETE` viene annullato e non perdi i dati.

**`ingest_site_period(period_type, start, end)`**: per ogni settimana (lunedì-domenica) o mese, una query con **nessuna** dimensione e `date_ranges` pari al periodo, metriche `activeUsers, newUsers`. Torna una riga sola. Se `period_end` è dopo ieri, `is_complete = false`.

Perché una query per periodo: gli utenti unici di una settimana non sono la somma dei sette giorni (la stessa persona torna più volte), quindi non si ricavano dai giornalieri.

Cose da tenere presenti mentre scrivi:

- `run_query` restituisce **stringhe**: converti con `int()` e `float()` prima di scrivere.
- Riusa `parse_ga4_date` da `ga4_service.py` per la colonna `date` e scarta le righe malformate come fa il resto del codice.
- Default: ricarica gli ultimi 3 giorni, e per i periodi quello in corso e il precedente (GA4 rivede i dati recenti).
- Scrivi su `etl_run_log` all'inizio (`running`) e chiudi in un `try/finally` con `success` o `failed` più `error_message`. Una riga per fonte: `ga4_site_daily`, `ga4_channel_daily`, `ga4_site_period`. Se i canali falliscono e il sito no, il log deve dirlo. È ciò che permette al riquadro di salute di dire la verità.
- Scrivi anche una piccola funzione `iter_weeks(start, end)` che restituisce coppie lunedì-domenica. Test mentale: per il 15 ottobre 2026 l'ultima settimana va da 2026-10-12 a 2026-10-18 ed è incompleta.

Aggiungi il target Make (nel Makefile le righe di comando iniziano con **tab**):

```make
ingest-ga4-site: check-env venv up wait-db migrate
	cd ga4_client && DATABASE_URL=$(DATABASE_URL) GA4_PROPERTY_ID=$(GA4_PROPERTY_ID) ../$(VENV_BIN)/python ingest_ga4_site.py $(GA4_SITE_ARGS)
```

`GA4_SITE_ARGS` deve avere un default nel Makefile, come `GA4_ARGS`: `GA4_SITE_ARGS ?= --days 3`. Backfill: stesso intervallo del passo 1 per sito e canali, più le settimane e i mesi corrispondenti. Una sola esecuzione di `make ingest-ga4-site` li carica tutti e tre.

**Checkpoint.**
1. Confronta un giorno chiuso con l'interfaccia GA4 (utenti, sessioni, visualizzazioni): devono coincidere.
2. Utenti settimanali tra massimo e somma dei giornalieri. Deve restituire zero righe:

```sql
SELECT p.period_start, p.active_users, max(d.active_users) AS max_giorno, sum(d.active_users) AS somma_giorni
FROM fact_ga4_site_period p
JOIN fact_ga4_site_daily d ON d.metric_date BETWEEN p.period_start AND p.period_end
WHERE p.period_type = 'week' AND p.is_complete
GROUP BY p.period_start, p.active_users
HAVING p.active_users NOT BETWEEN max(d.active_users) AND sum(d.active_users);
```

3. Copertura: visualizzazioni degli articoli diviso visualizzazioni del sito per giorno. Non aspettarti 100%, perché il sito ha pagine che non sono articoli. Il valore reale che vedi qui serve a fissare la soglia di allerta (punto aperto del blueprint).
4. Riconciliazione dei canali: per ogni giorno la somma delle sessioni dei canali deve stare entro l'1% delle sessioni del sito. Deve restituire zero righe:

```sql
SELECT s.metric_date, s.sessions AS sito, sum(c.sessions) AS canali
FROM fact_ga4_site_daily s
JOIN fact_ga4_channel_daily c USING (metric_date)
GROUP BY s.metric_date, s.sessions
HAVING abs(sum(c.sessions) - s.sessions) > 0.01 * s.sessions;
```

5. I valori di `channel_group` che GA4 restituisce davvero, ordinati per peso. Ti servono per compilare il seed `dim_channel` del passo 9:

```sql
SELECT channel_group, sum(sessions) AS sessioni
FROM fact_ga4_channel_daily GROUP BY 1 ORDER BY 2 DESC;
```

---

## Passo 9 · Mart di Panoramica e Acquisizione

**Staging.** `stg_ga4_site_daily` e `stg_ga4_site_period`: solo rinomine (`metric_date` → `date_day`, `screen_page_views` → `page_views`, `user_engagement_duration` → `engagement_seconds`) e tipi.

**`mart_site_daily`** (denso, spine = `dim_date` nell'intervallo coperto, join a sinistra con le sessioni di sito; i giorni senza riga valgono zero per i componenti additivi).

- Rapporti ricalcolati dai componenti: `engagement_rate = engaged_sessions / nullif(sessions, 0)`, `engagement_seconds_per_user = engagement_seconds / nullif(active_users, 0)`. Denominatore zero dà `null`, non zero.
- Medie mobili a 7 giorni: `avg(x) over (order by date_day rows between 6 preceding and current row)` per i componenti.
- **Per i rapporti la media mobile non è la media dei rapporti.** `engagement_rate_ma7` è `sum(engaged_sessions)` su 7 giorni diviso `sum(sessions)` su 7 giorni. Esempio: lunedì 100 sessioni con il 50% coinvolte, martedì 10 sessioni con il 100%. La media dei due rapporti è 75%, il rapporto vero è 60 su 110, cioè 54,5%. I giorni piccoli non devono pesare quanto i grandi.
- Confronti con spostamento fisso, che funzionano perché la spine è densa: `_p7 = lag(x, 7)` e `_py = lag(x, 364)` (stesso giorno della settimana, un sabato contro un sabato).
- `is_provisional` per gli ultimi 2 giorni.
- `articles_views` (da `mart_article_daily`), `matching_coverage = articles_views / nullif(page_views, 0)`. Quando funziona, riporta `matching_coverage` anche in `mart_data_health`.

**Trappola.** `active_users` giornalieri non si sommano mai né tra giorni né tra periodi. La media mobile a 7 giorni di `active_users` è "utenti attivi medi al giorno": è lecita, ma l'etichetta nel dashboard deve dirlo.

**`mart_site_period`** (denso per tipo di periodo). Una riga per (`period_type`, `period_start`): componenti sommati da `stg_ga4_site_daily` nel periodo, `active_users` e `new_users` presi da `fact_ga4_site_period` (qui il valore del periodo è quello giusto). Rapporti ricalcolati. Qui il periodo è l'unità, quindi `_prev` è la riga prima della stessa `period_type` (`lag(x, 1) over (partition by period_type order by period_start)`) e `_py` è `lag(x, 52)` per le settimane e `lag(x, 12)` per i mesi. Riporta `is_complete`.

**Seed `dim_channel`.** `dbt/seeds/dim_channel.csv` con `channel_group,display_name,sort_order,is_organic`. Compilalo con l'elenco reale del checkpoint 5 del passo 8 (tipicamente Direct, Organic Search, Paid Search, Organic Social, Paid Social, Email, Referral, Organic Video, Display, Affiliates, Unassigned). `is_organic` è vero per i gruppi che iniziano con "Organic". `display_name` è l'etichetta italiana mostrata nel dashboard. Tieni `Unassigned` come riga a sé ("Non assegnato"): escluderlo farebbe sparire sessioni e il test di riconciliazione fallirebbe.

**`stg_ga4_channel_daily`**: stesse rinomine del sito. **`mart_channel_daily`** (denso: spine = `dim_date` × `dim_channel` nell'intervallo coperto, quindi un canale senza traffico in un giorno vale zero):

- Componenti: `sessions`, `engaged_sessions`, `new_users`, `page_views`, `engagement_seconds`, `active_users`.
- `sessions_share = sessions / nullif(sum(sessions) over (partition by date_day), 0)`: le quote dei canali di un giorno sommano al 100%.
- `engagement_rate = engaged_sessions / nullif(sessions, 0)`.
- `sessions_ma7` e `engagement_rate_ma7` (per il rapporto: somma delle sessioni coinvolte su 7 giorni diviso somma delle sessioni su 7 giorni, come per il sito).
- `_p7` e `_py` per `sessions`, `engaged_sessions`, `page_views`, con `lag(x, 7)` e `lag(x, 364) over (partition by channel_group order by date_day)`. Funzionano perché la spine è densa per ogni canale.
- `is_provisional` come per il sito, più le colonne del seed (`display_name`, `sort_order`, `is_organic`).

**Trappola.** `active_users` per canale non si somma mai tra canali. Nel mart resta come colonna di ciascun canale, ma non devono esistere né un totale utenti ottenuto sommando i canali né una quota sugli utenti. Il dashboard ragiona sulle **sessioni** e sulle quote di sessioni.

**Controlli.** In YAML con `dbt_utils`: `unique_combination_of_columns` su (`period_type`, `period_start`), `accepted_range` da 0 a 1 per `engagement_rate`. Un test singolare per la riconciliazione: le visualizzazioni degli articoli non superano quelle del sito in nessun giorno. Il test sui canali: le sessioni dei canali sommano alle sessioni del sito per ogni giorno, tolleranza 1% (è la query del checkpoint 4 del passo 8, resa test, severità `error`). Un secondo test con severità `warn` segnala i `channel_group` presenti nella fact ma assenti da `dim_channel`.

**Checkpoint.** `dbt build` verde. I numeri della settimana più recente completa in `mart_site_period` coincidono con la stessa settimana nell'interfaccia GA4. In `mart_channel_daily` le quote di un giorno sommano a 100% e il canale Organic Search di un giorno chiuso coincide con quello del rapporto "Acquisizione del traffico" di GA4.

---

## Passo 10 · Orchestrazione e controlli

**Fai tu.** Nel Makefile devono esserci quattro target: `ingest-recent` (passo 1), `ingest-ga4-site` (passo 8), `dbt-build` e `refresh`. Gli ultimi due:

```make
dbt-build:
	cd dbt && ../$(VENV_BIN)/dbt build --profiles-dir .

refresh: ingest-recent
	$(MAKE) ingest-ga4 GA4_ARGS="--days 3"
	$(MAKE) ingest-ga4-site GA4_SITE_ARGS="--days 3"
	$(MAKE) dbt-build
```

L'ordine è la regola: prima gli articoli (altrimenti GA4 non aggancia quelli nuovi), poi GA4 per articolo, sito e canali, e solo alla fine le trasformazioni. Se un'ingestione fallisce `make` si ferma e i mart restano all'ultima versione valida.

**Perché `GA4_ARGS="--days 3"`.** Il default di `make ingest-ga4` è 30 giorni, cioè 30 chiamate a GA4 a ogni esecuzione, e dopo il backfill basta ricaricare gli ultimi giorni (GA4 li rivede). Il passaggio per `$(MAKE)` serve a sovrascrivere la variabile solo dentro `refresh`. **Trappola trovata con un dry run (`make -n refresh`):** la mia prima versione passava `GA4_DAYS=3` e il refresh ricaricava comunque 30 giorni. Il motivo è l'`export` nudo in cima al Makefile, che esporta ogni variabile già espansa (`GA4_ARGS` = "--days 30") nell'ambiente del sub-make, e `?=` non sovrascrive una variabile d'ambiente già definita. Per questo si passa `GA4_ARGS` intero da riga di comando. Prima di fidarti di un target ricorsivo, guardalo sempre con `make -n`. Il backfill lungo resta un'operazione manuale, con `GA4_ARGS` esplicito. Il canale viene aggiornato da `ingest-ga4-site` con la stessa finestra di 3 giorni, e grazie al "cancella e reinserisci" i giorni rivisti non lasciano righe orfane.

**Come verificare che la pipeline raccolga i canali.** Dopo un `make refresh`, la query seguente deve mostrare tre righe (una per fonte GA4 nuova) con `status = 'success'` e `finished_at` di pochi minuti fa:

```sql
SELECT source, status, rows_written, finished_at FROM etl_run_log ORDER BY run_id DESC LIMIT 6;
```

**Pianificazione.** Windows Task Scheduler una volta al giorno chiama `make refresh`. Ricorda il punto aperto 6: il computer deve essere acceso. Se non lo è, il riquadro di salute lo segnalerà perché `mart_data_health` è una vista che legge `now()`.

**Allerta.** In Metabase, un alert sulla carta basata su `mart_data_health` quando `status` non è `ok`. Aggiungi un `pg_dump` giornaliero (stesso comando del passo 0) prima del `dbt-build`.

**Documentazione.** In `dbt_project.yml` imposta `+persist_docs: {relation: true, columns: true}` per scrivere le descrizioni dei modelli come commenti Postgres, e scrivi le descrizioni in italiano nei file `.yml`.

---

## Quattro decisioni tue

Ti serve una risposta su queste prima di consegnare, perché cambiano i numeri.

| Decisione | Mia raccomandazione |
| --- | --- |
| Priorità delle sezioni | Tieni quella provvisoria per sbloccarti e portala alla redazione con le 13 sezioni sotto gli occhi |
| Rapporti su intervallo libero (es. tempo di coinvolgimento per visualizzazione dei primi articoli) | Il blueprint vieta le formule nel BI, ma un rapporto di somme su un intervallo scelto dall'utente non può stare in una tabella già calcolata. Ammettiamo un'unica eccezione: una domanda SQL di Metabase che fa `sum(a) / nullif(sum(b), 0)` con la stessa formula del glossario |
| `comment_count` e `was_modified_in_week` | Fuori dalla fase 1. Se servono, prima va scritto lo script che popola `fact_wp_engagement_weekly`: ad oggi nessuno lo fa |
| Dimensione GA4 per i canali | `sessionDefaultChannelGroup`, come nel blueprint. Verificala con `getMetadata` e fissala **prima** del backfill: cambiarla dopo spezza lo storico |

## Dopo questa guida

Coinvolgimento per sezione, Pubblico (device e paese) e SEO (Search Console) richiedono nuove fonti. Le affrontiamo come terza release, riusando lo stesso schema di lavoro.
