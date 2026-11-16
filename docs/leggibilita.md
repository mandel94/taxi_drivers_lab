# Leggibilità dei testi: regole e lezioni apprese

File generato da `python -m nlp.leggibilita documento`: non modificarlo a mano. Le regole stanno in `nlp/leggibilita/regole.md`, il glossario in `nlp/leggibilita/dati/glossario.json`, gli eventi in `nlp/leggibilita/dati/eventi.jsonl`.

## Come si misura
- Indice Gulpease (per l'italiano, 0-100): almeno 60 (sopra 80 facile, 60-80 licenza media, sotto 40 difficile).
- Frasi di al massimo 25 parole, al massimo 6 numeri e 1 parentesi per testo, al massimo 90 parole, niente gergo del glossario.
- Il controllo misura la forma, non l'utilità: dopo averlo superato il testo va comunque riletto da una persona.

## Come si usa
```
python -m nlp.leggibilita check --file testo.txt        # misura, esce con 1 se non passa
python -m nlp.leggibilita migliora --file testo.txt     # correzioni meccaniche e cosa riscrivere a mano
python -m nlp.leggibilita riscritto --prima a.txt --dopo b.txt   # registra una riscrittura riuscita
python -m nlp.leggibilita feedback "non capisco X" --termine X --semplice Y
python -m nlp.leggibilita documento                    # rigenera questo file
```
Ciclo: scrivere, misurare, correggere o riscrivere, rimisurare, finché non passa; registrare la riscrittura e ogni feedback ricevuto.

## Regole di scrittura
- Scrivi come parleresti a un collega che non ha visto i dati: soggetto, verbo, una sola idea per frase.
- Prima cosa è successo, poi cosa fare. Il numero serve a sostenere l'idea, non a riempire il testo.
- Al massimo 6 numeri per testo e 3-4 per idea. Arrotonda ("il 10%, di solito il 4%") e dai a ogni numero un solo confronto.
- Frasi sotto le 25 parole. Se serve un elenco, spezza in più frasi invece di usare i due punti e le parentesi.
- Una sola parentesi per testo. Mai sigle interne (H-01, P-04, R-07) nei testi per i lettori.
- Niente gergo statistico (mediana, coorte, baseline, pattern, "z =" e simili): usa la parola semplice del glossario.
- Dì "lettori" o "utenti", non il nome delle colonne. Titoli di film e serie tra apici singoli.
- Distingui sempre ciò che si sa, ciò che si pensa e ciò che si propone, ma con una parola ("probabilmente", "da verificare"), non con una sigla.
- Se un testo non passa il controllo si riscrive e si ricontrolla fino a che passa; ogni riscrittura e ogni feedback si registrano.
- Un testo che passa il controllo può comunque essere inutile: la rilettura di una persona resta l'ultima verifica.

## Problemi più frequenti
Testi controllati: 14; non passavano al primo colpo: 2.
Punteggio medio Gulpease: 68.1 prima, 69.1 dopo.

| Problema | Volte |
|---|---|
| troppi numeri | 2 |
| troppe parentesi | 2 |
| indice Gulpease basso | 1 |
| frase troppo lunga | 1 |

## Esempi prima e dopo

- Prima (Gulpease 58): Un pezzo nuovo vive nella settimana d'uscita: dei 175 usciti nei primi tre giorni con almeno 15 utenti, solo il 26% è ancora in lista la settimana dopo e fanno il 18% dei lettori della prima (vale per tutte e cinque le coppie di settimane; Festival 17% su 58 pezzi). La spinta (home, social, newsletter) va nel giorno d'uscita. Si farà, Trailers e Live Streaming On Demand resistono di più (53-70%, 9
  Dopo (Gulpease 68): Un articolo nuovo fa quasi tutti i suoi lettori nella settimana in cui esce. La settimana dopo ne resta meno di un quinto (18%, su 175 articoli). Conviene quindi spingerlo su home, social e newsletter il giorno stesso. Fanno eccezione i 'si farà', i trailer e i film in streaming, che la gente continua a cercare. Lì è meglio aggiornare l'articolo già esistente.

- Prima (Gulpease 63): Categorie: salgono Interviste (9,9% degli utenti attivi contro 4,0% di norma) e, più lievemente, Recensioni (9,0% contro 6,1%). Scende Si farà (13,6% contro 22,2% di norma; la settimana scorsa era al 32% per due annunci grossi). Festival di Cinema (20,9%), Live Streaming On Demand, News, Serie TV, Trailers e Speciali e Magazine restano in linea. Il salto delle Interviste è di due pezzi sui registi
  Dopo (Gulpease 67): Le interviste sono andate meglio del solito: il 10% dei lettori, di solito il 4%. Un po' meglio anche le recensioni. Gli articoli sui 'si farà' sono andati peggio: 14% contro il 22% abituale, perché senza notizie nuove hanno avuto pochi lettori.

## Feedback ricevuti
- 2026-11-16 (Manuel, 16/11/2026): Gli insight non si capiscono, non credo che un umano possa capirli: serve un requisito minimo di leggibilità.
- 2026-11-16 (Manuel, 16/11/2026): Gli insight non sono utili: devono dire cosa fare, non descrivere cosa è successo.
- 2026-11-16 (Manuel, 16/11/2026): 'in lista la settimana dopo' non si capisce → termine 'in lista': ancora tra gli articoli letti
- 2026-11-16 (controllo automatico, 16/11/2026): Troppi numeri e frasi lunghe: i puntini della sintesi avevano 10-18 numeri e frasi fino a 59 parole → termine 'coppie di settimane': confronti tra due settimane di fila

## Glossario (gergo e alternativa semplice)

| Gergo | Meglio |
|---|---|
| baseline | base di confronto |
| confondente | altra causa possibile |
| confondenti | altre cause possibili |
| coorte | gruppo |
| coorti | gruppi |
| coppie di settimane | confronti tra due settimane di fila |
| correlazione | legame |
| deviazione | variazione |
| in lista | ancora tra gli articoli letti |
| mediana | cifra tipica |
| mediane | cifre tipiche |
| mediani | tipici |
| mediano | tipico |
| outlier | valore fuori dal normale |
| pattern | andamento che si ripete |
| percentile | posizione in classifica |
| quartile | quarto dei casi |
| reach | lettori raggiunti |
| regressione | stima |
| retention | quanti restano |
| ritenzione | quanti restano |
| significativa | netta |
| significative | nette |
| significativi | netti |
| significativo | netto |
| sopravvivenza | quanti restano |
| varianza | variazione |
