# Profilo di stile del Trend Radar

Strumenti per far scrivere a un modello i titoli delle sezioni e le parti di cornice del Trend Radar (intro, "Prima di lasciarci", "Uno sguardo d'insieme") nello stile di Manuel De Luzi, e per controllare il risultato. Il compito è un'**imitazione dello stile d'autore** (*authorship style imitation*): si scrive un testo nuovo, a partire dal materiale della settimana, nello stile di un autore. Non è uno *style transfer* in senso stretto, che riscrive un testo esistente cambiandone lo stile e tenendo il contenuto.

Questo file spiega come si usa. Le scelte di metodo, la taratura e i limiti sono in [docs/metodologia_profilo_stile.md](../../docs/metodologia_profilo_stile.md).

## Le parti

| File | Livello | Cosa fa |
| --- | --- | --- |
| `profilo_stile.md` | 1, qualitativo | Regole prescrittive con esempi reali. È il testo che il modello legge |
| `build_prompt.py` | 1 + esempi | Compone il prompt: istruzioni, profilo, le cornici vere degli ultimi 3 articoli, 23 coppie "apertura della sezione → titolo", materiale della settimana |
| `metriche_target.yaml` | 2, quantitativo | Intervalli delle metriche per sezione, calcolati con spaCy. Generato, non va modificato a mano |
| `divieti.yaml` | 2 | Formule da non usare, cercate nel testo e nei titoli. Livello `vietato` (mai nei tuoi testi) o `raro` |
| `metrics.py` | 2 | `build` calcola gli intervalli; `check` controlla un testo (cornice e titoli) e scrive il report |
| `stylometry.py` | 2 | Distanza d'insieme (Cosine Delta sulle 100 parole più frequenti) dai tuoi testi, confrontata con 60 articoli di altri autori del sito |
| `titles.py`, `metriche_titoli.yaml` | 2 | Titoli delle sezioni: forma (struttura, ancora, lettura, lunghezza, punteggiatura) e punteggio contro i titoletti degli altri autori. `build`, `analyze`, `check` |
| `corpus.py`, `parsing.py` | dati | Estraggono dal warehouse gli articoli divisi per sezione (`data/`), con i corsivi dei titoletti e i titoletti degli altri autori |

Tre articoli restano fuori dal profilo (`config.HOLDOUT_IDS`: 552807, 561483, 565041). Servono solo a verificare che il profilo funzioni su testi che non ha visto.

## Il giro: genera, confronta, correggi

Dalla root del progetto, con il database acceso.

1. Aggiorna corpus e intervalli (solo quando escono nuovi Trend Radar):

   ```bash
   .venv\Scripts\python.exe -m nlp.style_profile.corpus
   ```

   ```bash
   .venv\Scripts\python.exe -m nlp.style_profile.metrics build
   ```

   ```bash
   .venv\Scripts\python.exe -m nlp.style_profile.titles build
   ```

   `metrics build` avvisa se un divieto `vietato` compare nei tuoi testi: in quel caso non è un tic estraneo e va tolto o declassato a `raro`. Per un rapporto sui titoli di addestramento (strutture, ancore, cosa distingue i tuoi titoli dagli altri) c'è `titles analyze`.

2. Prepara il prompt. Per una settimana nuova, dal tuo materiale:

   ```bash
   .venv\Scripts\python.exe -m nlp.style_profile.build_prompt --materiale appunti.md
   ```

   Per una prova su un articolo hold-out, con il materiale ricavato dall'articolo (senza i titoli delle sezioni, che li genera il modello) e la cornice e i titoli originali salvati a parte:

   ```bash
   .venv\Scripts\python.exe -m nlp.style_profile.build_prompt --da-holdout 565041
   ```

   Con `--con-titoli` il materiale riporta i titoli veri.

3. Dai il prompt (`giri/prompt_<nome>.md`) a un modello **che non abbia visto gli originali** e salva la risposta in `giri/<nome>_generato.md`.

4. Controlla:

   ```bash
   .venv\Scripts\python.exe -m nlp.style_profile.metrics check nlp\style_profile\giri\565041_generato.md
   ```

   Per controllare solo i titoli (un titolo per riga, anche "1. ..." o "## ..."):

   ```bash
   .venv\Scripts\python.exe -m nlp.style_profile.titles check nlp\style_profile\giri\565041_titoli_generati.md
   ```

5. Confronta il generato con l'originale (`giri/<id>_originale.md` e `giri/<id>_titoli_originali.md`) leggendo i testi affiancati. Dove il generato tradisce la differenza, correggi `profilo_stile.md` con una regola e un esempio, o aggiungi un pattern a `divieti.yaml`. Rifai i passi 2-4. Dopo due o tre giri il profilo dovrebbe stabilizzarsi.

### Formato del materiale

Markdown libero. Il costruttore lo passa al modello così com'è. Conviene includere:

- le date della settimana;
- le sezioni del corpo in ordine, con il titoletto e il testo (o almeno le note su ogni titolo), perché l'intro le riassume nello stesso ordine;
- gli URL degli articoli da rilanciare in "Prima di lasciarci", **con una riga di nota per ciascuno** (cosa dice di più dell'URL: chi lo produce, dove si vede, un giudizio). Senza note il modello ricava la voce dallo slug e la ricopia: il controllo lo segnala (sezione "Voci di Prima di lasciarci e URL").

`giri/565041_materiale.md` è un esempio completo.

### Formato del testo da controllare

```markdown
## Titoli delle sezioni
1. <titolo della sezione 1, con i titoli delle opere in *corsivo*>
2. ...

## Intro
<due paragrafi>

## Prima di lasciarci
- <voce>

## Uno sguardo d'insieme
<un paragrafo>
```

Il blocco `## Titoli delle sezioni` si controlla a parte (vedi sotto). Se manca, ogni altro `## Titoletto` seguito da un testo viene letto come una sezione del corpo: se ne confronta il testo con gli intervalli del corpo e il titolo con le regole dei titoli.

## Come leggere il report

- **Metriche per sezione.** "ok" sta dentro l'intervallo abituale (p10-p90); "ai margini" sta dentro il minimo e il massimo dei tuoi testi; "sotto/sopra" sta fuori da tutto il corpus. Sezioni di 80-120 parole oscillano molto: conta uno scarto che si ripete da un giro all'altro, non il singolo valore.
- **"Prima di lasciarci"** ha solo 4 elenchi di riferimento: intervalli stretti, scarti attesi anche sui tuoi testi.
- **Divieti.** Il segnale più netto: un testo generato riuscito non ne ha nessuno.
- **Titoli.** Per ogni titolo: struttura, ancora, lettura, punteggio e segnalazioni. Il punteggio è un log-rapporto: sopra 0 il titolo somiglia ai tuoi titoli più che ai titoletti degli altri autori del sito. **Da solo non basta** (un titolo con i due punti può avere un punteggio positivo): contano le segnalazioni. "Ai margini" è un avviso lieve, tutto il resto vale di più. Sull'insieme si controlla che i titoli siano 4-6 e che la quota di ancore "nome" e di titoli "ancora, lettura" sia quella degli ultimi 5 numeri, con la tolleranza di un titolo.
- **Distanza stilometrica.** Riassume molti tratti in un numero. Il riferimento degli altri autori è fatto di recensioni e news, cioè di un genere diverso: la misura separa bene "cornice di Trend Radar" da "articolo qualunque del sito", meno bene il tuo stile da una cornice generica ben impostata.

## Taratura (14/11/2026)

Prova sull'articolo hold-out 565041 (cornice originale contro una cornice scritta apposta nello stile generico di un modello):

| | Originale | Controllo negativo |
| --- | --- | --- |
| Intro: metriche nell'intervallo abituale | 22 su 26 | 18 su 26 |
| Prima di lasciarci | 19 su 26 | 18 su 26 |
| Sguardo d'insieme | 22 su 26 | 12 su 26 |
| Divieti trovati | 0 | 17 |
| Distanza stilometrica (tuoi testi: 0,59-0,87) | 0,79, nel raggio | 0,88, appena fuori |

Divieti, sguardo e intro distinguono; "Prima di lasciarci" e la stilometria distinguono poco. Le prime due prove su testo generato (565041 e 561483, 15/11/2026) sono nel [documento di metodo](../../docs/metodologia_profilo_stile.md), §10: sulla forma il testo regge, restano il "ci" in ogni frase dell'intro e le voci dell'elenco costruite sugli slug.

### Titoli (15/11/2026)

Sugli stessi tre hold-out e su un controllo negativo (titoli con i due punti, la maiuscola a ogni parola, il trattino e il punto finale):

| | 565041 | 561483 | 552807 | Controllo negativo |
| --- | --- | --- | --- | --- |
| Punteggio medio (tuoi titoli: mediana +3,4) | +4,4 | +1,4 | +1,5 | −0,8 |
| Titoli con una segnalazione oltre "ai margini" | 1 su 4 | 0 su 4 | 0 su 5 | 4 su 4 |

Il punteggio separa i tuoi titoli dai titoletti del sito (AUC 0,91 leave-one-out, 0,87 sui 13 titoli di hold-out), ma da solo non ha fermato il controllo negativo: tre titoli su quattro avevano un punteggio positivo. Sono le regole di punteggiatura, maiuscole e formule a segnalarli tutti. Il 552807 viene segnalato sull'insieme perché è del vecchio formato (nessuna ancora "nome").
