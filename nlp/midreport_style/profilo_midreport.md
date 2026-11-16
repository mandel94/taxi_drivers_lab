# Profilo di stile: midreport per Sandra

Fonte: 15 report inviati (dic 2025 - 9 nov 2026) in `corpus/`; il formato di riferimento è quello stabile dalla settimana 38 in poi (set 2026), con la metrica "utenti attivi" dalla settimana 41. Dati grezzi: `profilo_dati.json` (script `profilo.py`).

## Struttura (in quest'ordine)
1. **Oggetto**: `TaxiDrivers Analytics: Midreport Settimana NN (G-G mese AAAA)` (per esempio "2-6 nov 2026").
2. **Destinatari**: Sandra Orlando, direzione Taxi Drivers, Gianluca Di Stefano.
3. **Saluto**: `Ciao Sandra, ciao Vincenzo, ciao Gianluca,`
4. **Apertura**: `vi mando il midreport per la settimana NN (dal G al G mese).`
5. **`In sintesi:`** con 3-4 puntini (mediana 3-4, 80-190 parole in tutto). Ogni puntino è un'osservazione con un numero a sostegno (quota % di utenti attivi della categoria, confronto con la settimana scorsa, utenti attivi, engagement, secondi di lettura). Si cita un titolo in corsivo; si spiega la causa (festival, picco della settimana scorsa, evergreen). Tono: colloquiale, sobrio, prima persona plurale/singolare, nessuna enfasi.
6. **Categorie**, in grassetto con i due punti, sempre nello stesso ordine: Si farà, Serie TV, Live Streaming On Demand, News, Festival di Cinema, Speciali e Magazine, Interviste, Recensioni, Anticipazioni, Trailers. Una categoria senza articoli si omette; 3 articoli per categoria (2 se mancano).
7. **Voce articolo**: `• *'Titolo'* (score: NN) → X utenti attivi, Y% engagement, Zs.` Score intero; engagement in %; secondi con "s".
8. **`Nota:`** una riga (0-3 per report) dopo la categoria, solo per outlier: articolo con molti utenti ma score basso, evergreen presente da settimane, profilo search confermato. Formula: `Nota: *'Titolo'* (score: NN, X utenti attivi) → Y% engagement, Zs. <una frase di contesto>.`
9. **Grafico**: `Qui sotto trovate il trend delle visualizzazioni, ...` con una frase sul perché (crescita, picco da bot rientrato...). Il grafico è `newplot.png` (trend visualizzazioni, linea di tendenza verde).
10. **Chiusura**: `Una buona serata,` / `Manuel De Luzi` / `--` / link LinkedIn e Linktree (firma fissa).

## Regole di contenuto
- I titoli sono quelli del sito, tra apici singoli nel nome dell'opera.
- Escludere sempre "5 attrici...pornostar" e gli articoli "streaming gratis".
- Italiano: accenti corretti, "Si farà" con la f minuscola.
- Mai superlativi o promesse; si segnalano anche i cali ("Si farà scende dal 31% al 13%").
- Quando i dati sono dubbi (incidente sito, bot) lo si dice nella frase del grafico.

## Evoluzione (non replicare)
- Prima della settimana 41 la metrica era `views` e lo score aveva decimali (58.05); da allora `utenti attivi` e score intero.
- I report di dicembre-febbraio erano più brevi e senza categorie standard.
- Allegato Excel: `classifica_articoli_week NN.xlsx` (nei mesi prima `top_N_articles_week N.xlsx`).
