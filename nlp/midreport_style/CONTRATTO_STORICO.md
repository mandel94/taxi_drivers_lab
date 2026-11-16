# Contratto: storico dei midreport e xlsx per la KB

Due moduli puri (nessun DB, nessuna rete). Test in `tests/test_midreport_storico.py` (import con sys.path su `ga4_client`, come in `tests/test_midreport_report.py`).

## A. `ga4_client/midreport_storico.py`
Lo storico conserva il midreport **come consegnato** (non i dati grezzi). Due file in una cartella `midreports/`:
- `midreports.jsonl`: una riga JSON per settimana (UTF-8, LF, ordinata per `week_id`).
- `midreport_items.csv`: una riga per articolo/Nota, colonne esatte: `week_id,category,kind,rank,title,score,users,engagement,duration_s,metric`. `kind` = `item` (rank 1..n) o `nota` (rank 0). `engagement` 0-1, `duration_s` secondi, `users` = utenti attivi o views (vedi `metric`).

| Funzione | Comportamento |
|---|---|
| `build_record(start, end, subject, sintesi, sections, notes, insights=None, chart_sentence="", reliability_warning=None, category_stats=None, n_articles=None, metric="utenti", drive_folder_id=None, gmail_draft_id=None, source="workflow")` | dict con `week_id` = `start.isoformat()`, `period_start`, `period_end`, `iso_week`, `subject`, `sintesi` (lista), `insights` (lista, `[]` se None), `chart_sentence`, `reliability_warning`, `category_stats`, `n_articles`, `metric`, `drive_folder_id`, `gmail_draft_id`, `source`, e `sections`/`notes` ridotti a `{categoria: [{title, score, users, engagement, duration_s}]}` (le righe in ingresso hanno le colonne di `midreport_client.HEADERS`: `activeUsers`, `engagementRate`, `averageSessionDuration`, `editorial_score`; per le Note la lista ha un solo elemento) |
| `items_rows(record)` | lista di dict con le colonne di `midreport_items.csv` |
| `upsert_week(folder, record)` | crea la cartella, aggiorna `midreports.jsonl` sostituendo la riga con lo stesso `week_id` (idempotente) e riscrive `midreport_items.csv` da tutti i record; UTF-8, LF; ritorna il percorso del jsonl |
| `load_weeks(folder)` | lista di record ordinata per `week_id`; `[]` se il file non esiste |
| `parse_sent_report(text, email_date)` | `text` = corpo di un report inviato in testo semplice (con o senza asterischi Markdown), `email_date` = `datetime.date` di invio; ritorna un record con `source="gmail"`. Periodo: da "(G-G mese AAAA)" nell'oggetto/riga di apertura o da "dal G al G mese"; se manca, lunedì-venerdì della settimana precedente alla data di invio (lunedì della settimana di `email_date` meno 7 giorni). `sintesi` = puntini sotto "In sintesi" (righe a capo unite); categorie = righe `*Nome:*` o `Nome:` seguite da voci `• 'Titolo' (score: N) → X utenti attivi|views, Y% engagement, Zs.` (anche a capo); righe `Nota:` = note della categoria corrente; `metric` = `utenti` se compare "utenti attivi", altrimenti `views`; `chart_sentence` = paragrafo con "trend" |

## B. `ga4_client/midreport_report.py` (aggiunte)
| Funzione | Comportamento |
|---|---|
| `kb_filename(start, end)` | `top_articles_by_category_20261102_20261106.xlsx` |
| `write_kb_xlsx(df, path)` | xlsx per `insight_kb.py ingest`: foglio unico, colonne `title, editorial_score, publication_date, author, category, activeUsers, screenPageViews, engagementRate, averageSessionDuration, pagePath` con `pagePath = "/<article_id>/"` (colonna `article_id` del df); titoli esclusi scartati; ordine per `activeUsers` decrescente |

`midreport_client.build_top` guadagna il parametro opzionale `with_article_id=False`: se True aggiunge in coda la colonna `article_id` (default invariato: `write_template` non cambia).
