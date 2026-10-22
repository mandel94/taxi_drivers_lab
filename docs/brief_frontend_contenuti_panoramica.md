# Brief front-end · Dashboard TaxiDrivers, tab Contenuti, Panoramica e Acquisizione

Documento per chi progetta il layout e costruisce le carte in Metabase. Non serve conoscere la parte back-end: qui trovi i dati che arriveranno, le regole da rispettare e una proposta di layout. Il back-end è descritto in [guida_backend_contenuti_panoramica.md](guida_backend_contenuti_panoramica.md).

**Stato dei dati.** Tutti i mart elencati sotto sono costruiti nello schema `marts` dal 19 ottobre 2026 e si aggiornano ogni giorno alle 07:30. Le colonne di questo documento sono quelle reali. Le release 1 e 2 indicano solo l'ordine in cui sono nati.

**Copertura reale dei dati** (al 19 ottobre 2026), che condiziona cosa si può mostrare:

| Dato | Da quando | Conseguenza per il layout |
| --- | --- | --- |
| Sito, canali, utenti su periodo (Panoramica, Acquisizione) | 1 agosto 2025 | Il confronto con l'anno prima (`_py`) è disponibile dal 31 luglio 2026 per i mart giornalieri e da agosto 2026 per settimane e mesi |
| Dati per articolo (Contenuti) | 16 agosto 2026 | Circa 9 settimane: il confronto con l'anno prima (`_py`) è `null` per tutto il tab Contenuti fino ad agosto 2027. Il confronto con la settimana prima (`_prev`) funziona |
| Settimane complete in Contenuti | dal 17 agosto 2026 | La prima settimana (10 agosto) e quella in corso sono marcate incomplete |
| Commenti e modifiche per articolo | non disponibili | Non progettare carte su commenti: la tabella sorgente è vuota |

Il confronto con l'anno prima in Contenuti sarà vuoto per mesi: progetta lo stato "n.d." come stato normale, non come eccezione.

| Release | Tab | Mart |
| --- | --- | --- |
| 1 | Contenuti | `mart_article_daily`, `mart_article_weekly`, `mart_section_weekly`, `mart_content_weekly`, `mart_data_health` |
| 2 | Panoramica e Acquisizione | `mart_site_daily`, `mart_site_period`, `mart_channel_daily` (e `matching_coverage` in `mart_data_health`) |

---

## 1. Regole che valgono per tutte le carte

1. **Nessuna formula nel BI.** Ogni numero è già calcolato nei mart. Le carte leggono colonne, sommano e filtrano. Un'unica eccezione concordata: i rapporti di somme su intervallo libero (vedi glossario), scritti come domanda SQL con la formula indicata.
2. **Solo lo schema `marts`.** Non collegare le tabelle `public`: contengono dati grezzi non adatti alla lettura.
3. **`null` non è zero.** Un confronto con l'anno prima senza storico è `null`: mostralo come "n.d." con una spiegazione al passaggio del mouse ("storico disponibile dal 16/08/2026"), mai come 0 o come una variazione del -100%.
4. **Metriche "attribuite".** `sessions_attributed` e `engaged_sessions_attributed` contano una sessione per ogni articolo visitato. Mostrale sempre con l'etichetta "attribuite agli articoli" e mai sommate a livello sezione. Visualizzazioni e tempo di coinvolgimento si sommano ovunque senza avvertenze.
5. **Giorni provvisori.** `is_provisional = true` marca gli ultimi 2 giorni, che GA4 può ancora rivedere. Nelle serie temporali tratteggiali o escludili (interruttore, default: esclusi). Non usarli per i confronti.
6. **Settimane incomplete.** `is_complete_week = false` marca la prima settimana (dati che partono a metà) e l'ultima, che include ancora giorni provvisori. Distinguile visivamente o escludile dai KPI di testa. Attenzione a una sfumatura: in `mart_site_period` il flag `is_complete` significa solo "il periodo è terminato", quindi può essere vero per una settimana che in `mart_section_weekly` o `mart_content_weekly` è ancora `is_complete_week = false` (perché contiene gli ultimi 2 giorni provvisori). Per i KPI di testa usa il flag del mart che stai leggendo e, se mostri affiancati dati di mart diversi, scegli la regola più prudente (settimana completa in entrambi).
7. **Confronti già calcolati e con spostamento fisso.** Le colonne `_py` (stesso periodo un anno prima, allineato al giorno della settimana), `_p7` (7 giorni prima, solo mart giornalieri) e `_prev` (settimana o mese prima, solo mart settimanali e per periodo) sono valori di riga. Se sommi `x` e `x_py` sullo stesso filtro date ottieni correttamente "periodo contro anno prima". **Non esiste** un "periodo precedente di pari lunghezza" per intervallo libero: non provare a costruirlo con un secondo filtro.
8. **Formati italiani.** Numeri con punto per le migliaia (`62.138`), decimali con la virgola, percentuali con un decimale. I secondi di coinvolgimento si mostrano come `h:mm:ss` o "12 h 30 min" a seconda dell'ordine di grandezza; scegli una regola e applicala ovunque.
9. **Variazioni.** Mostra sempre sia la variazione assoluta sia quella percentuale solo se il valore di base è significativo (nascondi la percentuale se la base è 0 o `null`). Non affidare il significato solo al colore verde/rosso: aggiungi segno e freccia.

---

## 2. Contratto dati

Tutti i mart usano le stesse chiavi di filtro: `date_day`, `week_start_date` (il lunedì), `section_key`, `age_bucket`, `channel_group`. Così un filtro globale vale su tutte le carte che hanno quella colonna.

### Release 1 · Contenuti

**`mart_article_daily`** · una riga per articolo e giorno **con traffico** (sparso: l'assenza di riga vale zero).
`date_day`, `week_start_date`, `article_id`, `title`, `link`, `published_date`, `section_key`, `section_name`, `age_days`, `age_bucket`, `is_new_30d`, `views`, `engagement_seconds`, `sessions_attributed`, `engaged_sessions_attributed`, `is_provisional`.

**`mart_article_weekly`** · una riga per articolo e settimana con traffico (sparso).
`week_start_date`, `article_id`, `title`, `link`, `section_key`, `section_name`, `age_bucket` (al lunedì, minimo 0), `weeks_since_publication`, `active_days`, `views`, `engagement_seconds`, `sessions_attributed`, `engaged_sessions_attributed`, `is_complete_week`.

**`mart_section_weekly`** · una riga per sezione e settimana (denso: 13 sezioni, ogni settimana coperta, anche con zero).
`week_start_date`, `section_key`, `section_name`, `views`, `engagement_seconds`, `articles_active`, `articles_published`, `views_per_active_article`, `views_share`, `is_complete_week`, più `views_prev`, `views_py`, `engagement_seconds_prev`, `engagement_seconds_py`, `articles_active_prev`, `articles_active_py`.
`views_share` è la quota sul totale delle visualizzazioni attribuite agli articoli (le quote delle sezioni sommano al 100%), non sul sito.

**`mart_content_weekly`** · una riga per settimana (denso).
`week_start_date`, `views_total`, `views_new_30d`, `views_archive`, `share_new`, `top10_share`, `articles_active`, `is_complete_week`, più `_prev` e `_py` per `views_total`, `views_new_30d`, `views_archive`.

**`mart_data_health`** · una riga per fonte, è una vista (sempre aggiornata).
`source` (cinque valori: `ga4_articles`, `ga4_site_daily`, `ga4_channel_daily`, `ga4_site_period`, `wp_articles`), `last_loaded_at`, `last_covered_date`, `days_missing_last_30`, `hours_since_load`, `last_run_status` (`success`, `failed` o `null`), `matching_coverage`, `status` (`ok`, `warn`, `error`), `status_message` (testo italiano pronto da mostrare, ad esempio "Dati aggiornati" o "2 giorni mancanti negli ultimi 30").
`matching_coverage` è valorizzata solo nella riga `ga4_articles`: quota delle visualizzazioni di sito spiegata dagli articoli sugli ultimi 30 giorni chiusi (oggi circa il 71%).
Per il riquadro in testa a ogni tab: mostra la riga con lo stato peggiore e il suo `status_message`; `error` va in evidenza. `warn` è normale quando manca un giorno e si risolve da solo alla prossima esecuzione.

Fasce di età (`age_bucket`, valori in quest'ordine): `0-7`, `8-30`, `31-90`, `91-365`, `366+`.
Sezioni (13): News, Recensioni, In Sala, Cult Movies, Animazione, Festival di Cinema, Trailers, Serie TV, Guide e Film da Vedere, Speciali e Magazine, Live Streaming On Demand, Rubriche, Interviste. Esiste anche `non_classificato`.

### Release 2 · Panoramica

**`mart_site_daily`** · una riga per giorno (denso).
`date_day`, `week_start_date`, `active_users`, `new_users`, `sessions`, `engaged_sessions`, `page_views`, `engagement_seconds`, `engagement_rate`, `engagement_seconds_per_user`, `is_provisional`, `articles_views`, `matching_coverage`.
Medie mobili a 7 giorni con suffisso `_ma7` per `active_users`, `new_users`, `sessions`, `page_views`, `engagement_seconds`, `engagement_rate`, `engagement_seconds_per_user`.
Confronti `_p7` e `_py` per `active_users`, `new_users`, `sessions`, `page_views`, `engagement_seconds`, `engagement_rate`.

**`mart_site_period`** · una riga per (`period_type`, `period_start`), con `period_type` = `week` o `month` (denso).
`period_type`, `period_start`, `period_end`, `is_complete`, `active_users`, `new_users`, `sessions`, `engaged_sessions`, `page_views`, `engagement_seconds`, `engagement_rate`, `engagement_seconds_per_user`, più `_prev` e `_py` per ciascuna.
In questa tabella gli utenti sono gli **utenti unici del periodo** letti da GA4: sono il valore giusto per un KPI di settimana o di mese. Non sommarli tra periodi.

**`mart_channel_daily`** · una riga per canale e giorno (denso: ogni canale in ogni giorno coperto, anche con zero).
`date_day`, `week_start_date`, `channel_group`, `display_name`, `sort_order`, `is_organic`, `sessions`, `engaged_sessions`, `new_users`, `page_views`, `engagement_seconds`, `active_users`, `engagement_rate`, `sessions_share`, `is_provisional`, più `sessions_ma7`, `engagement_rate_ma7`, e `_p7` e `_py` per `sessions`, `engaged_sessions`, `page_views`.
Le quote `sessions_share` dei canali di un giorno sommano al 100%. Usa `display_name` (etichetta italiana) e `sort_order` per ordinare legende e tabelle. Il gruppo "Non assegnato" (`Unassigned`) esiste e va mostrato con quell'etichetta, non nascosto.
**`active_users` è per canale e non si somma tra canali**: non mostrare mai un totale utenti ottenuto sommando i canali e non calcolare quote sugli utenti. Ragiona su sessioni e quote di sessioni.
I gruppi di canali li decide GA4 e possono aumentare: se ne compare uno nuovo, appare nei dati con la sua etichetta grezza finché non viene aggiunto all'elenco. Non fissare i colori su una lista chiusa: prevedi un colore neutro per i canali non previsti.

---

## 3. Glossario delle metriche

Usalo per le etichette e i suggerimenti al passaggio del mouse.

| Etichetta | Colonna | Cosa è | Si può sommare? |
| --- | --- | --- | --- |
| Visualizzazioni | `views`, `page_views` | Pagine viste | Sì, ovunque |
| Tempo di coinvolgimento | `engagement_seconds` | Secondi in cui la pagina è stata in primo piano | Sì, ovunque |
| Utenti attivi | `active_users` | Utenti che hanno interagito col sito | No: mai tra giorni o periodi |
| Nuovi utenti | `new_users` | Utenti alla prima visita | Sì, tra giorni |
| Sessioni (sito) | `sessions` | Visite al sito | Sì, tra giorni |
| Sessioni attribuite | `sessions_attributed` | Sessioni che hanno toccato l'articolo | No tra articoli |
| Tasso di coinvolgimento | `engagement_rate` | Sessioni coinvolte diviso sessioni | No: si ricalcola dai componenti |
| Tempo di coinvolgimento per utente | `engagement_seconds_per_user` | Secondi totali diviso utenti attivi | No |
| Visualizzazioni per articolo attivo | `views_per_active_article` | Visualizzazioni diviso articoli con almeno una visualizzazione | No |
| Quota sezione | `views_share` | Visualizzazioni della sezione sul totale degli articoli | No |
| Quota nuovi | `share_new` | Visualizzazioni da articoli con meno di 30 giorni sul totale | No |
| Quota dei primi 10 | `top10_share` | Visualizzazioni dei 10 articoli più letti sul totale | No |
| Copertura dell'aggancio | `matching_coverage` | Visualizzazioni degli articoli sul totale del sito | No |
| Quota sessioni del canale | `sessions_share` | Sessioni del canale sul totale delle sessioni del giorno | No |
| Utenti attivi per canale | `active_users` (in `mart_channel_daily`) | Utenti attivi che hanno avuto una sessione da quel canale | No: mai tra canali |
| Canale organico | `is_organic` | Vero per Organic Search, Organic Social, Organic Video | Le sessioni si sommano |

Rapporti su intervallo libero (l'eccezione della regola 1): tempo di coinvolgimento per visualizzazione = `sum(engagement_seconds) / nullif(sum(views), 0)`. Tasso di coinvolgimento = `sum(engaged_sessions) / nullif(sum(sessions), 0)`. Mai la media dei rapporti giornalieri.

---

## 4. Proposta di layout

È un punto di partenza: la gerarchia conta più dei dettagli.

**Struttura comune a entrambi i tab, dall'alto.**
1. **Riquadro di salute dei dati** (da `mart_data_health`): una riga sottile con "Aggiornato il …" e un indicatore per stato. Se `status` non è `ok`, deve diventare un avviso ben visibile.
2. **Barra dei filtri**, sempre visibile in scorrimento.
3. **Riga dei KPI.**
4. **Grafici**, dal più importante al meno.
5. **Tabella di dettaglio.**

### Panoramica

| Riga | Contenuto | Fonte |
| --- | --- | --- |
| Filtri | Intervallo date (default: ultimi 28 giorni completi). Interruttore "Includi giorni provvisori" (default: no). Selettore Settimana/Mese per i KPI | `date_day`, `period_type` |
| KPI | 6 carte: Utenti attivi, Nuovi utenti, Sessioni, Visualizzazioni, Tempo di coinvolgimento per utente, Tasso di coinvolgimento. Ciascuna mostra l'ultimo periodo **completo**, la variazione contro il periodo precedente e quella contro l'anno prima | `mart_site_period` (riga con `is_complete`, `_prev`, `_py`) |
| Tendenza | Linea con selettore metrica (Utenti, Sessioni, Visualizzazioni). Linea sottile per il valore giornaliero, linea marcata per la media mobile a 7 giorni, linea tratteggiata per lo stesso periodo dell'anno prima | `mart_site_daily` (`x`, `x_ma7`, `x_py`) |
| Settimane | Barre degli utenti attivi per settimana, con la settimana in corso distinta | `mart_site_period` (`period_type = 'week'`) |
| Qualità | Linea del tasso di coinvolgimento (media mobile), e a fianco la copertura dell'aggancio con una nota che la spiega | `mart_site_daily` |

I KPI di testa leggono il mart per periodo perché lì `_prev` e `_py` sono esatti. La tendenza legge il mart giornaliero.

### Contenuti

| Riga | Contenuto | Fonte |
| --- | --- | --- |
| Filtri | Intervallo date, Sezione (multipla), Fascia di età | `week_start_date`/`date_day`, `section_key`, `age_bucket` |
| KPI | 4 carte per l'ultima settimana completa: Visualizzazioni degli articoli, Tempo di coinvolgimento totale, Articoli attivi, Visualizzazioni per articolo attivo. Variazione contro la settimana prima e contro l'anno prima | `mart_content_weekly` (+ `mart_section_weekly` sommato) |
| Nuovi e archivio | Area impilata per settimana: visualizzazioni da articoli nuovi (30 giorni) e da archivio. Linea della quota dei nuovi | `mart_content_weekly` |
| Sezioni | Barre impilate per settimana e sezione. Accanto, tabella delle sezioni con visualizzazioni, quota, visualizzazioni per articolo attivo, variazione contro l'anno prima | `mart_section_weekly` |
| Età | Barre delle visualizzazioni per fascia di età | `mart_article_daily` |
| Classifica | Tabella dei primi 20 articoli dell'intervallo: titolo (con link), sezione, età, visualizzazioni, tempo di coinvolgimento. Ordinabile per visualizzazioni o per tempo | `mart_article_daily` raggruppata per `article_id` |

### Acquisizione

| Riga | Contenuto | Fonte |
| --- | --- | --- |
| Filtri | Intervallo date, Canale (multiplo), interruttore "Includi giorni provvisori" | `date_day`, `channel_group` |
| KPI | 4 carte sull'intervallo scelto: Sessioni (somma dei canali), Sessioni organiche (somma di `sessions` dove `is_organic`), Quota organica, Tasso di coinvolgimento. Ciascuna con la variazione contro lo stesso periodo dell'anno prima | `mart_channel_daily` (`sessions`, `is_organic`, `_py`). Quota e tasso sono rapporti di somme: eccezione alla regola 1 |
| Mix | Area impilata al 100% delle sessioni per canale nel tempo | `sessions_share` |
| Tendenza | Linea delle sessioni per canale (selettore), media mobile a 7 giorni e linea tratteggiata dell'anno prima | `sessions`, `sessions_ma7`, `sessions_py` |
| Tabella | Un canale per riga: sessioni, quota, tasso di coinvolgimento, variazione contro l'anno prima. Ordinata per `sort_order` o per sessioni | `mart_channel_daily` sommata sull'intervallo (rapporti di somme: eccezione alla regola 1) |
| Qualità | Tasso di coinvolgimento per canale, media mobile | `engagement_rate_ma7` |

Le sessioni sono l'unica metrica che somma correttamente tra canali. Evita grafici che sommano gli utenti attivi dei canali, anche solo per un totale in legenda.

**Quali filtri valgono dove.** Un filtro globale agisce solo sulle carte che hanno la colonna. Controlla la mappatura carta per carta in Metabase.

| Filtro | Panoramica | Contenuti | Acquisizione |
| --- | --- | --- | --- |
| Intervallo date | Sì | Sì | Sì |
| Sezione | Non applicabile (non esiste per il sito) | Sì | Non applicabile |
| Fascia di età | Non applicabile | Solo le carte che leggono i mart per articolo | Non applicabile |
| Canale | Non applicabile | Non applicabile | Sì |
| Provvisori | Sì | Sì (solo mart giornalieri) | Sì |

---

## 5. Stati da progettare

- **Dati vecchi o con buchi.** Il riquadro di salute cambia colore e testo; le carte restano visibili ma con avviso.
- **Storico mancante.** Le variazioni sull'anno prima mostrano "n.d." finché lo storico non è caricato: all'inizio lo saranno quasi tutte, perché i dati disponibili partono dal 16 agosto 2026 (il backfill è in corso lato back-end).
- **Filtri senza risultati.** Messaggio che dice quale filtro svuota la carta.
- **Settimana in corso.** Etichetta "in corso" e stile diverso, mai nei KPI di testa.
- **Zero.** Un 0 vero (nessuna visualizzazione per quella sezione in quella settimana) si mostra come 0.

---

## 6. Note pratiche per Metabase

- Metabase gira su `http://localhost:3000` (container `td_metabase`). Dopo ogni release: Admin → Databases → *Sync database schema now* e *Re-scan field values*, così lo schema `marts` compare.
- Preferisci domande SQL native con parametri di tipo "campo" (`{{date_range}}`, `{{section}}`) agganciati alle colonne del mart: l'interfaccia visuale va bene per le carte semplici, ma non costruire join o colonne calcolate.
- Convenzione dei nomi delle carte: `[Tab] Titolo`, ad esempio `[Contenuti] Visualizzazioni per sezione`.
- Le date dei mart sono già in fuso Roma: non applicare conversioni di fuso nelle carte.
- Un alert sulla carta della salute dei dati avvisa via mail quando lo stato non è `ok`. Lo configura chi gestisce il back-end.

---

## 7. Cosa NON è in questo giro

Coinvolgimento per sezione, Pubblico (device, paese) e SEO. Non progettare le loro carte ora: richiedono fonti dati che non esistono ancora.
