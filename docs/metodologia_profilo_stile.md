# Metodologia · Profilo di stile del Trend Radar

Documento di metodo per l'imitazione dello stile d'autore applicata alle parti di cornice del Trend Radar e ai titoli delle sue sezioni. Stato: **stile-v1 (cornice) e titoli-v1 (titoli), prototipi tarati; due prove su testo generato fatte il 15 novembre 2026 (§10)**. Il codice è in [nlp/style_profile](../nlp/style_profile/README.md), i test in [tests/test_style_profile.py](../tests/test_style_profile.py). Il README spiega come si lancia; questo documento spiega perché è fatto così.

---

## 1. In breve

Lo scopo è far scrivere a un modello linguistico i titoli delle sezioni, l'intro, l'elenco "Prima di lasciarci" e il paragrafo "Uno sguardo d'insieme" di un Trend Radar, in modo che non si distinguano da quelli scritti da Manuel De Luzi.

Il metodo ha due livelli separati:

1. **un profilo qualitativo**, scritto per il modello: regole prescrittive, ognuna con un esempio reale, più le cornici vere degli ultimi articoli come esempi;
2. **un controllo quantitativo**, che il modello non vede: metriche per sezione con intervalli ricavati dai testi dell'autore, un elenco di formule vietate e una distanza stilometrica d'insieme.

I titoli delle sezioni hanno un controllo a parte (§8): sono troppo brevi per le metriche delle altre sezioni, e si misurano per forma.

Si lavora a giri: si genera, si controlla, si confronta con un originale tenuto da parte, si corregge il profilo.

## 2. Il problema

**Che compito è.** È un'*imitazione dello stile d'autore* (authorship style imitation): si scrive un testo nuovo, a partire dal materiale della settimana, nello stile di un autore preciso. Non è uno *style transfer* in senso stretto, che riscrive un testo esistente cambiandone lo stile e tenendone il contenuto.

**Perché solo la cornice.** Le sezioni del corpo sono schede su un titolo, con fatti diversi ogni settimana. La cornice invece ripete ogni volta la stessa struttura e la stessa funzione: è la parte in cui lo stile pesa di più ed è anche la più facile da imitare male.

**Il corpus.** Manuel firma sul sito solo i Trend Radar: 16 articoli dal 21 luglio all'8 novembre 2026 (`articles_dim`, autore "Manuel De Luzi"). È tutto il materiale disponibile sul suo stile.

## 3. Da dove si parte e cosa è cambiato

La proposta di partenza prevedeva due livelli (profilo Markdown nel prompt, metriche YAML per il controllo). Prevedeva anche una costruzione in due passaggi: un'analisi articolo per articolo, poi una sintesi che tiene solo i tratti presenti in almeno metà dei pezzi. Infine un giro genera-confronta-correggi fino alla stabilità.

La struttura regge e resta. Sono cambiate sei cose:

| Scelta | Perché |
| --- | --- |
| **Esempi reali nel prompt**, oltre al profilo | Un modello imita molto meglio da esempi che da descrizioni. Con le sole regole tende alla caricatura: applica il tratto in ogni frase. Il profilo serve a dire ciò che gli esempi non rendono evidente, e i divieti |
| **Unità di analisi = sezione**, non articolo | Intro, elenco e sguardo hanno registri, lunghezze e persone verbali diversi. Una media sull'articolo non descrive nessuna delle tre. Le "varianti per genere" della proposta diventano "varianti per sezione" |
| **Hold-out** di tre articoli | Confrontare il generato con gli stessi testi da cui è nato il profilo è circolare: premia la copia |
| **Divieti verificati sul corpus** | Un "tic da modello" che l'autore usa davvero non è un tic. Ogni divieto viene cercato nei suoi testi prima di essere applicato |
| **Distanza stilometrica** | Riassume in un numero molti tratti che le metriche guardano uno alla volta. Ha un termine di paragone esterno (altri autori del sito) |
| **Analisi per articolo sostituita da conteggi** | La guida di stile esistente ([notes/guida_stile_trend_radar.md](../notes/guida_stile_trend_radar.md)) copriva già l'analisi qualitativa. La soglia "almeno metà dei pezzi" si applica contando automaticamente ogni tratto, articolo per articolo |

Scartato: il **fine-tuning** di un modello. Con 13 articoli di addestramento (circa 13.000 parole, di cui meno di 3.000 di cornice) il rischio di imparare a memoria è più alto del guadagno, e il profilo con gli esempi costa molto meno da aggiornare.

## 4. Corpus

### 4.1 Estrazione

`corpus.py` legge `content_html` da `articles_dim` e lo divide in sezioni con `parsing.py`. Il tipo di sezione si ricava dal titoletto:

| Titoletto | Tipo |
| --- | --- |
| nessuno (testo prima del primo H2) | `intro` |
| "Prima di lasciarci" | `prima_di_lasciarci` |
| "Uno sguardo d'insieme" | `sguardo` |
| "Gli spunti della settimana" (un solo numero, il precursore dell'elenco) | `spunti` |
| qualsiasi altro | `corpo` |

Ogni sezione ha due versioni del testo:
- **Markdown**, con corsivi, grassetti e link interni, perché la forma fa parte dello stile (i titoli delle opere vanno in corsivo);
- **testo piano**, per le metriche.

**Pulizia.** Il contenuto degli articoli è trattato come dato non fidato: a novembre il sito ha subito l'iniezione di script negli articoli.
- Si scartano script, stili, iframe e form.
- Si scartano le didascalie delle foto.
- Dei link si tengono solo quelli verso taxidrivers.it.
- Un titoletto vuoto non apre una nuova sezione.

Risultato: 16 articoli, 112 sezioni.

### 4.2 Divisione

| Insieme | Articoli | Uso |
| --- | --- | --- |
| Addestramento | 13 | Profilo, intervalli delle metriche, esempi nel prompt, riferimento stilometrico |
| Hold-out | 552807 (settembre, senza elenco), 561483 e 565041 (ottobre-novembre, con elenco) | Solo verifica. Non si leggono per scrivere il profilo |

La scelta copre i due formati in uso: prima e dopo l'introduzione di "Prima di lasciarci" (4 ottobre).

### 4.3 Termine di paragone

Sono 60 articoli di altri autori del sito, pubblicati dal 2026 con almeno 600 parole. Il campione è deterministico: ordinato per hash dell'id. Servono solo alla stilometria (§7).

## 5. Livello 1: il profilo qualitativo

File: [nlp/style_profile/profilo_stile.md](../nlp/style_profile/profilo_stile.md).

### 5.1 Come è costruito

1. **Base:** la guida di stile, che descriveva già formula d'apertura, schema dello sguardo, schemi delle voci dell'elenco e convenzioni.
2. **Riscrittura prescrittiva.** Ogni regola dice cosa fare ("Scrivi una frase per ogni sezione, nello stesso ordine"), non cosa succede ("l'intro riassume le sezioni"). Ogni regola ha un esempio reale.
3. **Soglia di ricorrenza.** Ogni tratto candidato si conta sugli articoli di addestramento.
   - Diventa **regola** se compare in almeno 7 articoli su 13.
   - Resta **facoltativo** se compare in meno articoli: per esempio "Infine" nello sguardo (5/13) o il punto e virgola tra le frasi dell'intro (3/13).
   - Il conteggio è riportato tra parentesi nel profilo, così chi lo rilegge sa quanto pesa ogni regola.
4. **Numeri dal livello 2.** Lunghezze, numero di frasi e parole per frase vengono dagli intervalli delle metriche, non da stime.
5. **Evoluzione del formato.** Le forme dei soli numeri di luglio ("Nel complesso, la settimana…", l'apertura generica dell'intro) sono indicate come da non usare. Il profilo descrive il formato attuale.

### 5.2 Struttura

Segue lo schema della proposta, adattato:

1. Identità
2. Struttura dell'articolo
3. Apertura (intro)
4. Ritmo e sintassi (tabella per sezione)
5. Lessico
6. Argomentazione
7. Chiusura (sguardo)
8. Prima di lasciarci
9. Varianti per sezione
10. Divieti
11. Convenzioni da confermare

### 5.3 Il prompt

`build_prompt.py` compone quattro blocchi:

1. istruzioni e formato d'uscita;
2. il profilo intero;
3. le **cornici reali dei 3 articoli di addestramento più recenti** che hanno l'elenco finale, con i titoletti del corpo al loro posto (il testo del corpo è omesso), così il modello vede come l'intro ripercorre l'ordine delle sezioni;
4. il materiale della settimana: date, sezioni del corpo in ordine, URL da rilanciare.

Le istruzioni vietano di copiare le frasi degli esempi (salvo la formula fissa) e di inventare fatti non presenti nel materiale.

## 6. Livello 2: metriche e divieti

### 6.1 Metriche

`metrics.py` calcola 26 metriche per sezione con spaCy (`it_core_news_lg`):

| Gruppo | Metriche |
| --- | --- |
| Dimensione | parole, frasi, paragrafi (voci per l'elenco), parole per paragrafo |
| Ritmo | parole per frase (media, deviazione, massimo), quota di frasi ≤ 12 parole, quota di frasi ≥ 30 parole |
| Punteggiatura (ogni 1000 parole) | virgole, punti e virgola, due punti, trattini lunghi, parentesi, virgolette, punti di domanda |
| Sintassi | quota di frasi con soggetto prima del verbo principale; quota di frasi che attaccano con un connettivo ("mentre", "infine", "nel frattempo"…) |
| Voce | forme di 1ª e 2ª persona plurale ogni 1000 parole (dalla morfologia di spaCy) |
| Lessico | varietà lessicale MATTR su finestre di 50 parole; lunghezza media delle parole; quote di aggettivi, nomi, verbi |
| Forma | titoli in corsivo ogni 100 parole (dal Markdown) |

MATTR è la media mobile del rapporto tra parole diverse e parole totali. A differenza del rapporto semplice non dipende dalla lunghezza del testo, che qui va da 40 a 140 parole.

### 6.2 Intervalli e verdetti

Per ogni tipo di sezione si calcolano minimo, 10° percentile, mediana, 90° percentile e massimo sulle sezioni di addestramento. I risultati stanno in [metriche_target.yaml](../nlp/style_profile/metriche_target.yaml), versione `stile-v1`.

| Verdetto | Condizione |
| --- | --- |
| ok | dentro p10-p90 (con almeno 8 sezioni di riferimento), altrimenti dentro min-max |
| ai margini | fuori dall'intervallo abituale ma dentro min-max |
| sotto / sopra | fuori da tutto il corpus |

Le sezioni di riferimento sono 13 intro, 13 sguardi, 60 sezioni del corpo e 4 elenchi. Con 13 testi brevi i valori sono intervalli, non obiettivi. Uno scarto isolato non dice nulla; conta uno scarto che si ripete da un giro all'altro.

### 6.3 Divieti

[divieti.yaml](../nlp/style_profile/divieti.yaml) elenca 24 espressioni regolari, ognuna con un motivo. Sono di quattro tipi:
- aperture generiche;
- metadiscorso e annunci di chiusura;
- immagini decorative;
- aggettivi di giudizio vuoti e formule promozionali.

**Validazione.** `metrics build` cerca ogni divieto nel corpus intero. Cinque pattern compaiono, sempre nelle sezioni del corpo e una o due volte: "affascinante", "sfumature", "si inserisce nel", "non è un caso che", la struttura "non è solo X, ma Y". Non sono tic estranei all'autore e sono passati dal livello `vietato` al livello `raro`.
- Un `raro` nel testo generato viene comunque segnalato: nelle sezioni di cornice non compare mai.
- Un `vietato` trovato nel corpus fa scattare un avviso.

### 6.4 Voci di "Prima di lasciarci" e URL

Ogni voce dell'elenco linka un articolo del sito, e l'indirizzo contiene già il titolo di quell'articolo (lo slug). Alla prima prova su testo generato il modello, avendo solo gli URL, ha ricopiato lo slug nelle voci ("quando l'amore corre senza freni"). `metrics check` misura per ogni voce le **parole di fila in comune con lo slug**, senza contare il titolo dell'opera in corsivo (che nello slug c'è per forza).

- Nei 21 elenchi di addestramento il 19% delle voci ha 4 o più parole di fila in comune con lo slug e il 10% ne ha 5 o più (massimo 6).
- Una voce con 5 o più si segnala; il rapporto riporta la quota dell'elenco confrontata con il 19%.
- Nell'uso vero la cura è nel materiale: una riga di nota per ogni URL.

## 7. Stilometria

`stylometry.py` calcola la **Cosine Delta** sulle 100 parole più frequenti del corpus di riferimento, quasi tutte parole funzionali (articoli, preposizioni, pronomi, congiunzioni). Le parole funzionali sono il segnale classico dell'attribuzione d'autore, perché si usano senza pensarci e non dipendono dall'argomento.

**Procedura.**

1. **Unità di confronto.** Le stesse sezioni presenti nel testo da controllare: se il testo ha intro, elenco e sguardo, ogni articolo dell'autore contribuisce le sue tre sezioni concatenate. Gli articoli degli altri autori vengono tagliati alla stessa lunghezza media, perché la distanza dipende dalla lunghezza.
2. **Formula esclusa.** La frase d'apertura ("Se mai vi foste persi nel rumore…") è identica in ogni intro e viene tolta da tutti i testi. Lasciarla premierebbe chi la copia, non chi scrive come l'autore.
3. **Frequenze.** Frequenze relative delle 100 parole, standardizzate (z-score) sull'insieme di tutte le unità.
4. **Distanze.**
   - Ogni articolo dell'autore si confronta con il profilo costruito sugli altri suoi articoli (lascia-uno-fuori): è la variabilità normale dell'autore.
   - Ogni articolo di altri autori si confronta con il profilo dell'autore.
   - Il testo controllato si confronta con il profilo dell'autore.
   - La distanza è 1 meno il coseno tra i vettori.
5. **Verdetto.** Il testo è "nel raggio" se la sua distanza non supera la massima dell'autore, "più vicino a te" se resta sotto il 10° percentile degli altri autori, altrimenti "più vicino agli altri".

**Limite di questo riferimento.** Gli altri autori scrivono soprattutto recensioni e news, non cornici di Trend Radar. La misura separa quindi anche generi diversi, non solo autori diversi. Distingue bene una cornice da un articolo qualunque del sito, meno bene lo stile dell'autore da una cornice generica impostata correttamente (§10).

## 8. Titoli delle sezioni

I titoli delle sezioni sono gli H2 che aprono ogni scheda su un film, una serie o un festival ("*Balcanica*, riprendersi la propria musica"). L'analisi è del 15 novembre 2026.

### 8.1 Perché un metodo a parte

Un titolo ha 2-12 parole. I 55 titoli di addestramento sono circa 380 parole in tutto. Con questi numeri:

- le metriche del livello 2 non hanno senso: "frasi", "virgole ogni 1000 parole" o la varietà lessicale su una frase sola non misurano niente;
- la Cosine Delta sulle parole più frequenti (§7) non regge: gran parte del vocabolario dei titoli è il nome delle opere, diverso ogni settimana.

Quello che resta stabile è la **forma**: come è costruito il titolo, quanto è lungo, che punteggiatura usa, da cosa parte. È ciò che si misura, senza guardare l'argomento.

### 8.2 Corpus

- **73 titoli di sezione tematica** nei 16 articoli. Restano fuori i 5 del primo numero (21/07), che hanno titoletti generici di categoria e nessuna virgola, e gli H2 fissi ("Prima di lasciarci", "Uno sguardo d'insieme", "Gli spunti della settimana", un'etichetta usata una volta sola).
- **55 titoli di addestramento** e **13 di hold-out** (gli stessi tre articoli del §4.2).
- **1.449 titoletti di altri autori** (H2-H4 di articoli del sito dal 2026, senza doppioni, almeno 2 parole, al massimo 25 per autore perché due o tre autori ne scrivono la metà). Sono il termine di paragone.
- I titoletti conservano i **corsivi**, perché il titolo dell'opera è in corsivo nel titoletto, ma non sempre: dal numero dell'11/10 lo è in 7 casi su 9 nei numeri di addestramento.

### 8.3 Cosa si misura

`titles.py` analizza ogni titolo con spaCy e con pochi lessici chiusi.

| Caratteristica | Valori | Come si ricava |
| --- | --- | --- |
| Struttura | `ancora_lettura` ("*Fatherland*, lungo la strada della memoria"); `frase` ("Gli Emmy Awards premiano gli streamers"); `sintagma` ("Tra Locarno79 e cortometraggi sulla salute mentale"); `solo_titolo` ("*Have a seat*") | `ancora_lettura` se c'è una virgola o i due punti fuori da virgolette e parentesi; `solo_titolo` se è tutto in corsivo; `frase` se c'è un verbo finito (o un infinito al posto del predicato); altrimenti `sintagma` |
| Tipo di ancora | nome (opera, persona, gruppo), evento, piattaforma, categoria | L'ancora è il testo prima della virgola (o il soggetto prima del verbo). Evento, piattaforma e categoria si riconoscono da lessici chiusi; tutto il resto è "nome" |
| Tipo di lettura | clausola (ha un verbo finito), per-infinito, infinito, preposizione, congiunzione, sintagma | spaCy sulla sola lettura |
| Numeriche | parole, parole dell'ancora e della lettura, caratteri per parola, maiuscole interne | Le maiuscole interne sono parole comuni con la maiuscola dopo la prima, fuori dall'ancora e dal titolo di un'opera |
| Binarie | corsivo, "tra", verbo finito, inizia con un articolo, due punti, parentesi, virgolette, numeri, puntini | Il verbo finito conta solo nella lettura: un titolo d'opera può contenerne uno ("Se domani non torno") |
| Finale | nessuno, `?`, `…`, `.`, `:` | L'ultimo carattere |

Le classificazioni sono euristiche: i titoli delle opere sono una classe aperta, quindi un'ancora sconosciuta finisce in "nome". Le ho controllate a mano sui 68 titoli prima di usarle.

### 8.4 Cosa distingue i titoli dell'autore

Confronto tra i 55 titoli e i 1.449 titoletti degli altri autori. L'AUC dice quanto una singola caratteristica separa i due insiemi (0,5 = per niente, 1 = del tutto).

| Caratteristica | Autore | Altri autori | AUC |
| --- | --- | --- | --- |
| Parole della lettura (dopo la virgola) | 4,5 | 2,4 | 0,77 |
| Parole dell'ancora | 2,2 | 1,5 | 0,69 |
| Parole in tutto | 7,1 | 6,9 | 0,63 |
| Verbo finito | 36% | 19% | 0,59 |
| Inizia con un articolo | 25% | 46% | 0,40 |
| Due punti | 2% | 19% | 0,41 |
| Maiuscole interne | 0% | 13% | 0,45 |

Il titolo dell'autore **non è più lungo, è più costruito**: la stessa lunghezza complessiva degli altri, ma con una parte dopo la virgola che gli altri non hanno. Gli altri titoletti sono per lo più etichette ("Il cast", "La trama") o frasi con due punti.

**Punteggio d'insieme.** 14 caratteristiche discretizzate (struttura, tipo di ancora e di lettura, fasce di lunghezza, finale, "tra", articolo iniziale, verbo finito, virgolette, parentesi, due punti, maiuscole interne, corsivo) alimentano un Naive Bayes: per ogni titolo si somma il logaritmo del rapporto tra la probabilità della caratteristica nei titoli dell'autore e nei titoletti degli altri (lisciatura di Laplace). Sopra 0 il titolo somiglia ai titoli dell'autore.

| Misura | Valore |
| --- | --- |
| AUC leave-one-out (55 titoli contro 1.449) | 0,91 |
| AUC dei 13 titoli di hold-out, modello costruito sul solo addestramento | 0,87 |
| Titoli dell'autore (leave-one-out): mediana, 10° percentile | 3,4; 1,1 |
| Titoli degli altri: mediana, 90° percentile | −6,6; 2,0 |

Il punteggio è calcolato con un modello che non usa il vocabolario, così l'argomento (cinema, serie) non pesa. Resta una parte di genere: gli altri titoletti sono di recensioni, news e rubriche. Per ogni titolo il rapporto mostra le due caratteristiche che pesano di più contro, per sapere cosa correggere.

### 8.5 Il formato è cambiato

La stessa analisi, numero per numero, mostra un'evoluzione:

| Periodo | Titoli di sezione |
| --- | --- |
| Fino a metà settembre | Intestazioni di categoria: "Film in sala, non solo blockbuster", "Serie TV, Netflix esplora generi diversi", "Trailer, un nuovo heist drama su Apple TV+" (2-3 su 4-5) |
| Dal 27/09 | Il nome dell'opera: 74% dei titoli (23 titoli in 5 numeri). Gli altri sono un evento (17%) o una piattaforma (4%) |
| Dall'11/10 | Titolo dell'opera in corsivo quasi sempre; la lettura con l'infinito compare ("*Balcanica*, riprendersi la propria musica") |

Per questo gli intervalli di lunghezza e punteggiatura usano tutti i 55 titoli, mentre **la composizione dell'insieme** (quota di titoli con ancora "nome", quota di titoli "ancora, lettura", numero di titoli) si confronta con i soli 5 numeri dal 27/09 (`TITLES_RECENT_FROM`). Con 4-5 titoli a numero una quota si muove a scatti del 20-25%: la tolleranza è di un titolo oltre il minimo e il massimo osservati.

### 8.6 Il controllo

`titles check` (o `metrics check`, se il testo contiene un blocco `## Titoli delle sezioni`) restituisce, per ogni titolo, la struttura, il punteggio e le segnalazioni; poi quelle sull'insieme.

| Segnalazione | Quando |
| --- | --- |
| Lunghezza e lettura | Fuori dal 10°-90° percentile ("ai margini") o dal minimo e massimo del corpus. Non si applica a un titolo che è solo il nome di un'opera |
| Maiuscole interne | Parole comuni con la maiuscola dopo la prima (il segno dei titoli "Title Case") |
| Punteggiatura | Punto finale; virgolette dritte (nei titoli sono “ ”); trattino con spazi come separatore; due punti, parentesi, virgolette o puntini quando compaiono in meno del 5% dei titoli dell'autore |
| Valori mai visti | Una struttura, un tipo di ancora o di lettura, un finale che nei titoli dell'autore non compare |
| Formule | Le stesse di `divieti.yaml` ("Un Viaggio…", "affascinante") |
| Opera con un verbo d'azione | "*Wild Horse Nine* porta il golpe sull'Isola di Pasqua": un'opera o una persona soggetto di un verbo che non sia "essere" è in 2 titoli su 55 (nei tuoi titoli la trama non si racconta) |
| Insieme | Numero di titoli, quota di ancore "nome", quota di titoli "ancora, lettura", titoli duplicati; più della metà dei titoli sopra le 9 parole |

### 8.7 Taratura

Come per la cornice (§10): una cornice originale come controllo positivo e un controllo negativo scritto apposta nello stile generico di un modello ("*Dio ride*: quando la fede incontra la risata", titoli con la maiuscola a ogni parola, trattino, punto finale).

| | 565041 (originale) | 561483 (originale) | 552807 (originale) | Controllo negativo |
| --- | --- | --- | --- | --- |
| Punteggio medio | +4,4 | +1,4 | +1,5 | −0,8 |
| Titoli con almeno una segnalazione oltre "ai margini" | 1 su 4 (le parentesi di "(tutti)", mai nei titoli di addestramento) | 0 su 4 | 0 su 5 | 4 su 4 |
| Segnalazione sull'insieme | no | no | sì: nessuna ancora "nome" (numero del vecchio formato) | no |

**Lettura.**

- Il punteggio da solo **non basta**. Alla prima prova tre titoli su quattro del controllo negativo avevano un punteggio positivo (+3,2, +1,3, +1,3): i due punti e le maiuscole pesano poco nel modello perché nei titoli dell'autore c'è un esempio solo. Per questo sono state aggiunte le regole della §8.6 (due punti, trattino, punto finale, formule), che il controllo negativo ora fa scattare tutte.
- Il caso di 552807 è corretto: la composizione dell'insieme segnala che è un numero del vecchio formato.
- Il rapporto non ha ancora visto un titolo generato davvero dal prompt.

### 8.8 Generazione

`build_prompt` aggiunge al prompt:

- la richiesta di un blocco `## Titoli delle sezioni`, un titolo per sezione del materiale e nello stesso ordine; l'intro riprende le sezioni in quell'ordine;
- il §9 del profilo, con le regole di forma e gli esempi;
- **23 coppie "apertura della sezione → titolo"** dei 5 numeri recenti: il modello vede da quale testo l'autore è arrivato al titolo, che è l'informazione che serve per imitarlo.

Nei giri sull'hold-out il materiale non riporta i titoli (le sezioni sono "Sezione 1, 2…"): i titoli veri restano nel file dei titoli originali per il confronto.

## 9. Il ciclo di affinamento

1. Si prepara il prompt da un articolo hold-out (`build_prompt --da-holdout <id>`). Il materiale contiene ciò che l'autore aveva davanti: le date, le sezioni del corpo per intero, gli URL dell'elenco (senza le sue frasi). La cornice originale viene salvata a parte.
2. Si genera con un modello **che non abbia mai visto le cornici originali**. Un modello che le ha lette, anche solo in una conversazione precedente, è contaminato e il confronto non vale.
3. Si esegue `metrics check` sul generato.
4. Si leggono generato e originale affiancati.
5. Si corregge **dove sta la causa**:
   - una regola mancante o fraintesa va nel profilo, con un esempio;
   - una formula estranea va in `divieti.yaml`;
   - un esempio fuorviante si sostituisce cambiando la scelta degli esempi.
6. Si ripete. Si cambia articolo hold-out tra un giro e l'altro, per non adattare il profilo a un solo testo.

**Criterio di arresto (proposta, da confermare con l'uso).** Il profilo è stabile quando, per due giri consecutivi su hold-out diversi:
- non ci sono divieti;
- intro e sguardo hanno almeno 20 metriche su 26 nell'intervallo abituale (l'originale ne ha 22);
- la distanza stilometrica cade nel raggio dell'autore;
- la lettura affiancata non trova differenze sistematiche nuove.

## 10. Taratura

Prima di usare il controllo su un testo generato bisogna sapere se distingue. Sull'hold-out 565041 sono state confrontate due cornici:
- la **cornice originale** (controllo positivo);
- una **cornice scritta apposta nello stile generico di un modello**, con le formule tipiche (controllo negativo).

| | Originale | Controllo negativo |
| --- | --- | --- |
| Intro: metriche nell'intervallo abituale | 22 su 26 | 18 su 26 |
| Prima di lasciarci | 19 su 26 | 18 su 26 |
| Sguardo d'insieme | 22 su 26 | 12 su 26 |
| Divieti trovati | 0 | 17 |
| Distanza stilometrica (autore: 0,59-0,87) | 0,79, nel raggio | 0,88, appena fuori |
| Altri autori fuori dal raggio dell'autore | 100% | 98% |

**Lettura.**

- **Distinguono bene:** divieti, sguardo e intro.
- **"Prima di lasciarci":** non distingue. Con 4 elenchi di riferimento gli intervalli sono stretti, e anche l'originale sfora 7 metriche (le sue voci sono più lunghe di quelle di ottobre).
- **Stilometria:** separa nettamente l'autore dagli altri autori, ma il controllo negativo resta appena fuori dal raggio, perché di genere è comunque una cornice.

La taratura dei titoli è nel §8.7.

### Prove su testo generato (15 novembre 2026)

Due giri completi, ciascuno con un subagente nuovo che ha letto solo il prompt (nessun accesso ai file con gli originali) e il controllo completo sul risultato. Per ogni giro il materiale ricavato dall'articolo non riporta i titoli delle sezioni: li genera il modello.

| | Giro 1: 565041 | Giro 2: 561483 (dopo le correzioni) |
| --- | --- | --- |
| Titoli: parole (da confrontare con il massimo di 9) | 9, 10, 11, 10 | 8, 9, 6, 10 |
| Titoli che riassumono la trama | 1 su 4 | 0 su 4 |
| Titoli: punteggio medio (tuoi titoli: mediana +3,4) | +4,4 | +3,9 |
| Intro / Prima di lasciarci / Sguardo: metriche nell'intervallo abituale (su 26) | 24 / 20 / 20 | 24 / 21 / 21 |
| Divieti trovati | 0 | 0 |
| Distanza stilometrica (autore: 0,59-0,87) | 0,625, nel raggio | 0,685, nel raggio |
| Voci con 5+ parole di fila dallo slug dell'URL | 5 su 6 | 0 su 5 |
| Sequenze di 5 parole in comune con le cornici di addestramento, oltre la formula d'apertura | nessuna | solo "Festa del Cinema di Roma" |
| Sequenze di 5 parole in comune con la cornice originale, oltre la formula e i titoli dei film | nessuna | "una graphic novel di culto" (assente dal prompt: il materiale dice "omonima graphic novel di Ratigher") |

**Le correzioni** applicate dopo il giro 1 (e valide per il giro 2): tetto di 9 parole per i titoli, un'opera con un verbo d'azione si scrive "*Opera*, lettura", il titolo in corsivo sta dentro il link nelle voci dell'elenco, la voce non ripete lo slug. Nel controllo: la regola sul verbo d'azione, la segnalazione dei titoli lunghi e la misura dell'eco dello slug.

**Lettura.**

- Sulla forma il modello rispetta il profilo. Le tre deviazioni del giro 1 non si ripetono nel giro 2, ma sono articoli diversi e un solo tentativo ciascuno: il generatore non è deterministico, e il giro 2 non prova da solo che le correzioni funzionino.
- Residui del giro 2: (a) il "ci" è in tutte e 4 le frasi dell'intro (1ª plurale 37 ogni 1000 parole contro un 90° percentile di 23; nel giro 1 era 30): il profilo ora lo limita a due frasi su quattro, correzione non ancora provata; (b) il titolo 2 usa come ancora la sezione del festival ("Alice nella Città") invece del titolo, lungo 14 parole, del film; (c) le voci dell'elenco sono tutte plausibili ma si fondano sullo slug, quindi non portano l'informazione in più che hanno le voci originali (un produttore, un'uscita).
- Il controllo segnala "sopra" i titoli in corsivo dell'elenco e dello sguardo: nelle cornici dei due ultimi numeri (561483, 565041) il corsivo è presente su ogni voce, mentre negli elenchi di addestramento è raro (0-1,8 ogni 100 parole). È una convenzione cambiata, non un difetto del generato (§11).
- **I due hold-out usati sono ora sporchi.** Le correzioni vengono da quello che si è visto nel giro 1 (565041) e nel giro 2 (561483). Per la prossima verifica serve un articolo nuovo, o la rotazione del §12.

## 11. Limiti

| Limite | Effetto | Cosa fare |
| --- | --- | --- |
| Corpus piccolo (13 articoli, meno di 3.000 parole di cornice) | Intervalli larghi, regole contate su pochi casi | Ricalcolare a ogni nuovo Trend Radar (§12) |
| Solo 55 titoli di addestramento, 23 nel formato attuale | La composizione dell'insieme si basa su 5 numeri; una quota si muove a scatti del 20-25% | Tolleranza di un titolo; ricalcolare a ogni numero |
| Titoli: tipo di ancora e di lettura sono euristiche | Un nome sconosciuto finisce in "nome"; spaCy sbaglia su frasi di 3-4 parole | Controllate a mano sui 68 titoli; il rapporto elenca la classificazione di ogni titolo |
| Titoli: il termine di paragone sono i titoletti del sito | Il punteggio misura in parte il genere (rubriche, etichette) | Non leggerlo come un'attribuzione d'autore; contano le segnalazioni |
| Titoli: la "lettura" (tesi, logline, gioco col titolo) è giudicata a mano | Il controllo non sa se la lettura dice qualcosa di sensato | La legge chi rivede il testo; le categorie sono nel profilo, §9 |
| Convenzione del corsivo che cambia | Negli elenchi di addestramento il titolo dell'opera nelle voci è quasi sempre in tondo; nei due ultimi numeri (hold-out) è sempre in corsivo. Un testo che segue la convenzione nuova risulta "sopra" | Ricalcolare gli intervalli quando i due numeri entrano in addestramento (§12) |
| Giri su testo generato: due, un tentativo ciascuno | Il generatore non è deterministico; il miglioramento del giro 2 non è provato | Ripetere sui prossimi numeri, con più tentativi per giro |
| Fuga dall'hold-out nel profilo | Nella prima versione il profilo citava esempi dei tre articoli tenuti fuori (soprattutto del 565041): il confronto su quelli era viziato | Corretto il 15/11: tutti gli esempi del profilo vengono ora dai 13 articoli di addestramento. I giri fatti con la prima versione non valgono come verifica |
| Solo 4 elenchi "Prima di lasciarci" | Metriche dell'elenco poco affidabili | Leggerle come indicazione finché i numeri non superano 8 |
| Formato in evoluzione (luglio diverso da novembre) | Le metriche mescolano formati | Il profilo descrive il formato attuale; con più numeri si possono escludere i primi dagli intervalli |
| Sezioni brevi (40-140 parole) | Le metriche di punteggiatura oscillano molto | Contano gli scarti ripetuti, non il singolo valore |
| Riferimento stilometrico di genere diverso | La distanza misura anche il genere | Quando ci saranno cornici scritte da altri, o generate e scartate, usarle come riferimento |
| Errori di analisi di spaCy | Soggetto preverbale e persona verbale possono sbagliare su frasi lunghe | Usarle come tendenza, non come prova |
| Contaminazione del generatore | Un modello che ha letto gli originali li ricopia | Generare sempre in un contesto pulito |
| Hold-out che invecchiano | Fra qualche mese non rappresentano più il formato | Ruotarli (§12) |

## 12. Manutenzione

- **Nuovo Trend Radar pubblicato:** `corpus` e poi `metrics build`. Il nuovo articolo entra in addestramento.
- **Rotazione degli hold-out:** quando il formato cambia, o ogni due mesi, si spostano in `config.HOLDOUT_IDS` gli articoli più recenti. Gli intervalli si ricalcolano e i giri fatti prima non sono più confrontabili.
- **Versione del metodo:** `stile-v1` è scritta in `metriche_target.yaml`. Va incrementata quando cambiano le metriche, le soglie o la divisione addestramento/hold-out, così i report di versioni diverse non si confrontano per errore.
- **Titoli:** dopo `metrics build` si lancia anche `titles build`. Se il formato dei titoli cambia ancora, si sposta `TITLES_RECENT_FROM` in `config.py` al primo numero del nuovo formato.
- **Convenzioni aperte:** forma delle date nel titolo e nella formula, corsivo nel titoletto (profilo, §12). Una volta decise, si aggiornano profilo ed esempi.

## 13. Riferimenti

- J. Burrows, "Delta: a measure of stylistic difference and a guide to likely authorship", *Literary and Linguistic Computing*, 17(3), 2002.
- P. Smith, W. Aldridge, "Improving authorship attribution: optimizing Burrows' Delta method", *Journal of Quantitative Linguistics*, 18(1), 2011.
- S. Evert et al., "Understanding and explaining Delta measures for authorship attribution", *Digital Scholarship in the Humanities*, 32(suppl. 2), 2017.
- M. Covington, J. McFall, "Cutting the Gordian knot: the moving-average type-token ratio (MATTR)", *Journal of Quantitative Linguistics*, 17(2), 2010.

## 14. File

| File | Ruolo |
| --- | --- |
| `nlp/style_profile/config.py` | Autore, hold-out, percorsi, campione di confronto, date dei titoli |
| `nlp/style_profile/parsing.py` | HTML e Markdown → sezioni tipizzate, con i corsivi dei titoletti |
| `nlp/style_profile/corpus.py` | Estrazione dal warehouse → `data/` (corpus, altri autori, titoletti degli altri) |
| `nlp/style_profile/titles.py` | Titoli delle sezioni: caratteristiche, Naive Bayes, `build`, `analyze`, `check` |
| `nlp/style_profile/metriche_titoli.yaml` | Intervalli dei titoli e formato attuale (generato) |
| `nlp/style_profile/profilo_stile.md` | Livello 1 |
| `nlp/style_profile/build_prompt.py` | Prompt e materiale da hold-out |
| `nlp/style_profile/metrics.py` | Livello 2: `build`, `check`, report |
| `nlp/style_profile/metriche_target.yaml` | Intervalli (generato) |
| `nlp/style_profile/divieti.yaml` | Formule vietate e rare |
| `nlp/style_profile/stylometry.py` | Cosine Delta |
| `nlp/style_profile/giri/` | Prompt, materiali, originali, report dei giri |
| `tests/test_style_profile.py` | 27 test, senza database |
