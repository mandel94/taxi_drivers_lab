# ETL giornaliero

Come si aggiornano i dati ogni giorno, come verificare che sia andato bene e cosa fare se no.

## Cosa fa

Ogni giorno alle **07:30** Windows lancia `scripts\run_refresh.cmd`, che apre MSYS2 ed esegue `make refresh`. Il refresh fa quattro passi indipendenti, in quest'ordine:

| Passo | Cosa | Come decide cosa caricare |
| --- | --- | --- |
| 1. `ingest-recent` | Articoli nuovi da WordPress | Si ferma quando incontra articoli già presenti |
| 2. `ingest-ga4 --auto` | GA4 per articolo (`fact_ga4_daily`) | Giorni senza righe da `GA4_ARTICLES_START` a ieri, più gli ultimi 3 |
| 3. `ingest-ga4-site --auto` | Sito, canali, utenti su settimana e mese | Dal giorno mancante più vecchio a ieri, più i periodi mai caricati o rimasti incompleti |
| 4. `dbt-build` | Staging, intermediate, mart, test | Ricostruisce tutto: ci vogliono circa 20 secondi |

Un passo che fallisce non ferma gli altri. Se qualcosa è fallito il codice di uscita finale è diverso da zero.

## Backfill dinamico: perché non si perde nulla

Le ingestioni GA4 non fidano di "ieri": a ogni esecuzione guardano cosa c'è davvero nelle tabelle.

- **Giorni mancanti:** un giorno senza nessuna riga viene caricato. Dopo un fermo (PC spento, GA4 non raggiungibile, un giorno fallito) la prima esecuzione utile recupera tutto.
- **Ultimi 3 giorni sempre ricaricati:** GA4 rivede i dati recenti.
- **Tetto per esecuzione:** per gli articoli (una chiamata GA4 al giorno) si recuperano al massimo 60 giorni mancanti per volta, dal più vecchio. Il resto viene recuperato nelle esecuzioni successive, quindi un buco di mesi non esaurisce la quota GA4.
- **Periodi:** una settimana o un mese salvato come incompleto e nel frattempo terminato viene rinfrescato.
- **Finestra di partenza (`floor`):** prima di `GA4_ARTICLES_START` (2026-08-16) e `GA4_SITE_START` (2025-08-01), definiti nel `Makefile`, non si cerca nulla. Per estendere lo storico basta anticipare queste date: alla prima esecuzione l'ETL carica da solo il pregresso, a blocchi.

Provato con un fermo simulato: cancellati due giorni interi da articoli, sito e canali, l'ETL li ha ritrovati e ricaricati con righe e totali identici.

## Come verificare

Nel dashboard: il riquadro di salute dei dati (`marts.mart_data_health`) mostra una riga per fonte con stato `ok`, `warn` o `error`.

A mano:

```sql
SELECT source, status, rows_written, date_from, date_to, finished_at
FROM etl_run_log ORDER BY run_id DESC LIMIT 8;

SELECT source, last_covered_date, days_missing_last_30, hours_since_load, status, status_message
FROM marts.mart_data_health;
```

Il log testuale è in `logs/refresh_AAAA-MM-GG.log` (se ne conservano 30 giorni).

## Lanciarlo a mano

Da Git Bash o da PowerShell, nella cartella del progetto:

```bash
bash scripts/run_refresh.sh          # come la pianificazione, con log
```

oppure, da MSYS2 UCRT64: `make refresh`. Singoli passi: `make ingest-recent`, `make ingest-ga4 GA4_ARGS="--auto --floor 2026-08-16"`, `make ingest-ga4-site GA4_SITE_ARGS="--auto --floor 2025-08-01"`, `make dbt-build`.

## Condizioni perché giri

- **Il PC deve essere acceso** e l'utente connesso all'ora pianificata. Se è spento l'attività parte appena possibile dopo l'accensione (impostazione "avvia appena possibile"), e il backfill dinamico recupera i giorni persi.
- **Docker Desktop**: se non risponde, lo script lo avvia e attende fino a 4 minuti.
- **Token GA4** (`ga4_client/token.json`): si rinnova da solo. Se Google lo invalidasse, l'ingestione GA4 fallirebbe e lo vedresti in `etl_run_log` e nel riquadro di salute. Rimedio: lanciare a mano un'ingestione GA4 da un terminale interattivo, che riapre il consenso nel browser.

## Cosa fare se fallisce

1. Guarda il log del giorno in `logs/` e `etl_run_log` (colonna `error_message`).
2. Rilancia: `bash scripts/run_refresh.sh`. È sicuro: le scritture sono idempotenti.
3. Se un solo passo fallisce ripetutamente, lancialo da solo (vedi sopra) per vedere l'errore completo.

Non serve nessun recupero manuale dei giorni persi: alla prima esecuzione riuscita vengono ricaricati.

## Gestire l'attività pianificata

```powershell
Get-ScheduledTask -TaskName "TaxiDrivers ETL giornaliero" | Get-ScheduledTaskInfo   # ultima e prossima esecuzione
Start-ScheduledTask -TaskName "TaxiDrivers ETL giornaliero"                          # lancio immediato
Disable-ScheduledTask -TaskName "TaxiDrivers ETL giornaliero"                        # sospende
Unregister-ScheduledTask -TaskName "TaxiDrivers ETL giornaliero" -Confirm:$false     # elimina
```

## Cosa non copre

- **Se il PC resta spento per giorni**, i dati non si aggiornano finché non si riaccende (poi recupera). Per un aggiornamento garantito serve una macchina sempre accesa o un container dedicato.
- **Dati per articolo prima del 16 agosto 2026**: non c'è backfill. Il confronto con l'anno prima per articolo e sezione resta `null` fino ad agosto 2027.
- **Articoli modificati dopo la sincronizzazione** non vengono riletti: `ingest-recent` carica solo quelli nuovi.
