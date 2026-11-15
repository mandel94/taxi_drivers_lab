# Regole di lavoro: contenere i consumi

Il 15/11/2026 il limite d'uso si è esaurito a metà di un lavoro: pacchetto `nlp/trend_publish` costruito con 16 sottoagenti, circa 220 test, prima di aver consegnato il risultato richiesto. Queste regole servono a non ripeterlo. Non c'è un contatore dei consumi: si stima prima.

## Ordine del lavoro
1. **Risultato prima, infrastruttura dopo.** Consegna ciò che serve oggi (per esempio il testo corretto e linkato). CLI, skill e riusabilità solo se richiesti, in un secondo momento.
2. **Preventivo per i lavori grandi.** Se prevedi più di 3 sottoagenti o più fasi in sequenza, scrivi in 3 righe fasi, sottoagenti e stima, e aspetta l'ok dell'utente.
3. **Un compito per sessione.** Chiuso un compito, proponi una nuova sessione: il contesto lungo si paga a ogni turno.
4. **Checkpoint su file.** A ogni fase aggiorna `STATO.md` nella cartella di output (fatto, da fare, comandi). Una sessione interrotta riparte da lì.
5. **Limite vicino:** finisci il pezzo in mano, salva lo stato, dillo e fermati.

## Sottoagenti
- Massimo 2-3 per fase, mai in parallelo senza averlo detto. Non servono per leggere pochi file o per risposte brevi.
- Prompt corti: rimanda a un file (per esempio un README con il contratto) invece di incollare le specifiche in ogni prompt.
- Chiedi un rapporto di al massimo 15 righe.
- `tester`, `executor` e `verifier` del plugin **non hanno una shell**: i test li lancia l'orchestratore.
- Modello economico per il lavoro meccanico (ricerche, test, esecuzioni); quello grande solo per le decisioni di progetto.

## Test
- Scrivi solo i test del contratto richiesto, senza casi extra. Un giro rosso-verde per modulo.
- Per ogni modulo scrivi test e codice nello stesso giro, così il gate di fine turno (`fast_test`) resta rosso il meno possibile: ogni fine turno in rosso richiama il turno.
- Esito dei test sempre con `| Select-Object -Last 5`.

## Output piccoli
- Mai stampare file interi o diff grandi: `git diff --stat`, `Select-Object -First/Last`, `Grep` con `head_limit`, `Read` con `offset` e `limit`.
- I file del repo usano fine riga LF: un file riscritto con CRLF segna ogni riga come modificata e gonfia il diff.
- Non rileggere ciò che è già nel contesto. Piccole modifiche con `Edit`, non riscrivendo il file intero.
- Query con `LIMIT` e tabelle compatte. Salva i risultati intermedi in file e riusali invece di rifare le analisi.
- `WebSearch` in modalità `standard`, solo quando serve.
- Risposte finali brevi: cosa è fatto, cosa resta, cosa serve dall'utente.
