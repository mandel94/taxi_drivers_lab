# Modulo di insight del midreport (fase 1: osservazioni)

Codice puro (pandas, nessuna rete, nessun DB). Produce FATTI con numero, campione e confronto
con lo storico. Nessuna conclusione: l'inferenza sta nella fase 2 (`inferenza.py`) e nella skill.

Sorgente: `articles_history.csv` della KB (`Insight KB`). Colonne usate: `week_id` (lunedi' ISO,
stringa), `period_start`, `period_end`, `window_days`, `comparable` (bool), `article_id`, `title`,
`author`, `category`, `pub_date`, `users`, `er` (0-1), `dur` (s), `excluded` (bool);
opzionale `pub_hour` (0-23, da articles_dim). Le righe `excluded` non entrano mai.
Le settimane con `comparable == False` non entrano in baseline e mediane.

Costanti in `observe.py`: `MIN_CATEGORY_ARTICLES = 5`, `MIN_USERS_ER = 20`,
`MIN_EXPOSURE_DAYS = 3`, `MIN_GROUP_N = 5`, `MIN_HISTORY_WEEKS = 4`.

## Funzioni (modulo `nlp/midreport_insight/observe.py`)

`classify_format(title, category) -> str`, primo che combacia, confronto senza maiuscole:
1. `'intervista'` se categoria `Interviste` o `intervista` nel titolo
2. `'trailer'` se categoria `Trailers` o `trailer` nel titolo
3. `'guida_lista'` se il titolo inizia (spazi ammessi, NIENTE virgolette) con numero di 1-2 cifre
   seguito da una parola, anche dopo `i|le|gli|top|ecco` (es. `10 serie tv sugli zombie`,
   `I 10 film Netflix`), oppure contiene `migliori|guida|classifica|dove vedere`, oppure un
   mese italiano seguito da anno a 4 cifre (es. `Disney+ Novembre 2026`)
4. `'recensione'` se categoria `Recensioni` o titolo inizia con `recensione`
5. `'si_fara'` se categoria `Si farà` o `si farà` nel titolo
6. `'anticipazione'` se categoria `Anticipazioni`
7. `'festival'` se categoria `Festival di Cinema`
8. `'news'` se categoria `News`
9. altrimenti `'altro'`

`extract_topic(title) -> str | None`: testo del primo segmento tra virgolette (`‘…’`, `'…'`,
`“…”`, `«…»`), con strip; l'apostrofo dentro la parola non chiude (`‘Highlander – L’ultimo
immortale’` -> `Highlander – L’ultimo immortale`). `None` se non ci sono virgolette.

`title_features(title) -> dict` con `has_question` (c'e' `?`), `starts_with_number` (inizia con
cifra, dopo eventuale articolo come sopra), `has_colon`, `n_chars`, `length_bucket`
(`corto` < 50, `medio` 50-80, `lungo` > 80), `topic` (extract_topic).

`build_table(history, week_id) -> DataFrame`: una riga per articolo della settimana (esclusi
`excluded`), colonne: `article_id, title, author, category, format, pub_date` (Timestamp),
`pub_weekday` (`lun`..`dom`), `pub_hour_bucket` (`notte` 0-5, `mattina` 6-11, `pomeriggio`
12-17, `sera` 18-23; `None` se manca `pub_hour`), `age_days` (period_start - pub_date, minimo 0),
`age_group` (`in_settimana` se pub_date >= period_start; poi `1-7gg`, `8-30gg`, `oltre_30gg`
sull'eta' in giorni a inizio periodo), `exposure_days` (giorni da max(pub_date, period_start) a
period_end inclusi), `users, er, dur`, le colonne di `title_features`, `baseline_users` (mediana
di `users` delle righe con stessa (categoria, age_group) nelle settimane comparabili diverse
da `week_id`, ognuna con l'age_group calcolato sul proprio period_start; NaN se meno di
`MIN_GROUP_N` righe), `ratio_vs_baseline` (users / baseline_users, NaN se baseline NaN),
`prev_week_id` (ultima settimana comparabile con week_id < `week_id`, None se non c'e')
e `prev_users` (utenti dello stesso article_id in quella settimana, NaN se assente).

`category_observations(table, history, week_id) -> list[dict]`, una per categoria presente,
ordinate per quota decrescente. Chiavi: `category, n_articles, users, share_pct` (quota sugli
utenti della settimana), `users_per_article, er_weighted` (media pesata sugli utenti),
`normal_share_pct, normal_users, normal_users_per_article` (mediane delle settimane comparabili
diverse da `week_id`; `None` se le settimane di storico con la categoria sono meno di
`MIN_HISTORY_WEEKS`), `share_delta_pp` (share - normal_share), `share_ratio` (share/normal),
`z` ((share - media storica)/deviazione standard storica, `None` se std 0 o storico corto),
`prev_share_pct` (settimana comparabile precedente, `None` se assente), `top1_title,
top1_share_of_category`, `n_history_weeks`, `sample_ok` (n_articles >= MIN_CATEGORY_ARTICLES),
`direction` (`'su'` se share_ratio >= 1.25, `'giu'` se <= 0.8, `'stabile'` altrimenti; `None`
se storico corto o `sample_ok` falso), `fact` (frase italiana con i numeri, senza cause).

`select_top_worst(table, per_cat=2) -> DataFrame`: per ogni categoria con almeno
`MIN_CATEGORY_ARTICLES` articoli, i `per_cat` articoli con piu' `users` (`role='top'`) e i
`per_cat` con `ratio_vs_baseline` piu' basso tra quelli con `exposure_days >= MIN_EXPOSURE_DAYS`,
`baseline_users >= 10` e non gia' top (`role='worst'`). Colonne della tabella piu' `role`.

`pattern_observations(table, history, week_id, min_n=MIN_GROUP_N) -> list[dict]`: per le
dimensioni `format, pub_weekday, pub_hour_bucket, age_group, length_bucket, has_question,
starts_with_number, has_colon, author`, per ogni valore con almeno `min_n` articoli con
`ratio_vs_baseline` valido: `dimension, value, n, median_ratio, median_users, median_er`
(solo righe con users >= MIN_USERS_ER, `None` se nessuna), `notable` (median_ratio >= 1.25 o
<= 0.8), `weeks_with_data` (settimane comparabili precedenti, piu' la corrente se comparabile,
in cui lo stesso valore ha almeno `min_n` articoli), `weeks_same_direction` (tra queste, quelle
con median_ratio dallo stesso lato di 1 della settimana corrente; ogni settimana e' calcolata
con `build_table` sulla sua baseline), `fact` (frase italiana con numeri, senza cause).
`author` solo per autori con almeno `min_n` articoli.

`observe_week(history, week_id, per_cat=2) -> dict` con `week_id, comparable, n_articles,
n_history_weeks, categories, patterns, top_worst` (lista di record, date in ISO), `flags` (lista
di stringhe: storico corto, settimana non comparabile, `pub_hour` assente).

CLI: `python -m nlp.midreport_insight.observe --week AAAA-MM-GG [--kb <cartella>] [--out <file>]`
scrive `osservazioni.json` (default `output/midreport_workflow/<settimana>/osservazioni.json`).
