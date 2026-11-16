# Contratto: modulo `ga4_client/midreport_report.py`

Funzioni pure (nessun DB, nessun GA4, nessuna rete), testate in `tests/test_midreport_report.py`. Import come in `tests/test_midreport_exclusions.py` (sys.path su `ga4_client`). Stile di riferimento: `profilo_midreport.md`.

Il DataFrame di ingresso ha le colonne di `midreport_client.HEADERS` (title, editorial_score, publication_date, author, category, activeUsers, screenPageViews, engagementRate, averageSessionDuration). Riusare `is_excluded_title` di `midreport_client`.

| Funzione | Comportamento |
|---|---|
| `CATEGORY_ORDER` | lista: Si farà, Serie TV, Live Streaming On Demand, News, Festival di Cinema, Speciali e Magazine, Interviste, Recensioni, Anticipazioni, Trailers |
| `week_label(start, end)` | `2-6 nov 2026`; a cavallo di mese `28 ott - 1 nov 2026`; mesi in italiano minuscolo abbreviati (gen feb mar apr mag giu lug ago set ott nov dic) |
| `subject(start, end)` | `TaxiDrivers Analytics: Midreport Settimana 45 (2-6 nov 2026)`; il numero è la settimana ISO di `start` |
| `build_sections(df, per_cat=3)` | dict categoria -> lista di righe (dict con le colonne), nell'ordine di `CATEGORY_ORDER`, prime `per_cat` per `editorial_score` decrescente, titoli esclusi scartati, categorie vuote o fuori ordine omesse |
| `build_notes(df, sections, min_users=50)` | dict categoria -> riga: l'articolo con più `activeUsers` della categoria, solo se NON è tra le righe di `sections` e ha `activeUsers >= min_users` |
| `category_stats(df)` | DataFrame/dict categoria -> quota % di `activeUsers` sul totale (esclusi i titoli esclusi), somma 100 (±0,1) |
| `format_item(row)` | `'Titolo' (score: 71) → 18 utenti attivi, 79% engagement, 47s.` score, utenti e secondi arrotondati a intero, engagement = rate*100 arrotondato |
| `format_note(row)` | `Nota: 'Titolo' (score: 62, 131 utenti attivi) → 52% engagement, 64s.` (il testo di contesto lo aggiunge la redazione) |
| `render_html(start, end, sintesi, sections, notes, chart_sentence, contesto_note=None)` | HTML per Gmail con stili inline (niente `<style>` né `<html>`): saluto `Ciao Sandra, ciao Vincenzo, ciao Gianluca,`, apertura `vi mando il midreport per la settimana NN (dal G al G mese).`, `In sintesi:` con `<ul><li>` per ogni stringa di `sintesi`, categorie in `<b>` con i due punti, titoli in `<i>`, note dopo la categoria, `chart_sentence`, chiusura `Una buona serata,` e firma `Manuel De Luzi` con link LinkedIn e Linktree. Mai la parola "views". Testo con escape HTML. |
| `write_classifica_xlsx(df, path)` | foglio `Dati`, intestazioni esatte: title, editorial_score, publication_date, author, category, activeUsers, engagementRate, averageSessionDuration; tabella `Tabella2` con ref `A1:H{n+1}`; freeze_panes `D1`; righe ordinate per `activeUsers` decrescente; titoli esclusi scartati; data come datetime; nome file di norma `classifica_articoli_week NN.xlsx` |
| `reliability_warning(end)` | stringa se `end >= INCIDENT_FROM` (2026-11-10, incidente sito), altrimenti `None` |

Esempio di riferimento (settimana 45): `classifica_articoli_week 45.xlsx` scaricato da Gmail nella cartella di sessione; usarlo solo come forma, i test usano dati finti.
