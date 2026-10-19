# Client WP REST API per taxidrivers.it

Documentazione di riferimento per il client Node.js che consuma la WP REST API di taxidrivers.it tramite il pacchetto [`wpapi`](https://github.com/WP-API/node-wpapi).

Riferimento ufficiale WordPress: https://developer.wordpress.org/rest-api/

---

## 1. Setup

```bash
npm install wpapi
```

Il client si basa su auto-discovery: al primo utilizzo, `WPAPI.discover()` interroga `https://www.taxidrivers.it/wp-json/`, legge i namespace e le route esposte dal sito, e configura automaticamente i metodi disponibili (incluse eventuali route custom).

```javascript
const { getSite } = require('./wp-client');

const site = await getSite();
const posts = await site.posts().perPage(5);
```

L'istanza è cacheata in memoria (singleton), quindi la discovery avviene una sola volta per processo, non ad ogni richiesta.

## 2. Struttura del progetto

| File | Responsabilità |
|---|---|
| `wp-client.js` | Istanza singola del client, auto-discovery, caching della connessione |
| `posts-service.js` | Funzioni di alto livello per query comuni (ultimi post, per categoria, ricerca) |
| `test-discovery.js` | Script di verifica manuale della connessione |

Best practice: il resto dell'applicazione non deve mai chiamare `wpapi` direttamente, ma passare sempre dal layer di servizio. Questo isola il resto del codice da eventuali cambi futuri (es. cambio libreria, aggiunta cache, gestione errori centralizzata).

## 3. Best practice generali per l'uso della WP REST API

### 3.1 Limitare sempre i campi restituiti

Ogni richiesta di lista dovrebbe usare `_fields` per evitare di scaricare l'intero oggetto post (che include `content.rendered` completo anche quando non serve):

```javascript
site.posts().param('_fields', 'id,title,link,date');
```

Motivazione: riduce peso della risposta e tempo di parsing, specialmente su liste lunghe.

### 3.2 Usare `_embed` solo quando servono i dati collegati

`_embed` include in un'unica risposta autore, immagine in evidenza e termini di tassonomia, evitando richieste N+1. Va usato solo se questi dati servono davvero, perché appesantisce comunque il payload rispetto a una richiesta senza embed.

```javascript
site.posts().embed(); // autore, immagine, tassonomie in un colpo solo
```

### 3.3 Paginare sempre esplicitamente

Il default di `per_page` è 10. Per liste potenzialmente lunghe, impostare sempre `perPage()` e gestire la paginazione leggendo gli header di risposta (`X-WP-Total`, `X-WP-TotalPages`), non assumendo mai che una singola richiesta ritorni tutto.

### 3.4 Non ripetere la discovery

`WPAPI.discover()` fa una richiesta HTTP aggiuntiva prima di poter usare il client. Va eseguita una volta sola e l'istanza va riutilizzata per tutta la vita del processo (vedi pattern singleton in `wp-client.js`).

### 3.5 Gestire la cache lato server

Il sito usa WP Rocket come plugin di caching: le risposte potrebbero non riflettere immediatamente una pubblicazione appena avvenuta. Se il client necessita di dati sempre aggiornati (es. dopo una pubblicazione), va previsto un meccanismo di retry o un parametro di cache-busting concordato con chi gestisce il sito.

### 3.6 Verificare tassonomie e custom post type prima di sviluppare

Le sezioni del sito (Recensioni, Serie TV, Festival, ecc.) potrebbero essere categorie standard oppure tassonomie o post type custom. Prima di scrivere query specifiche, verificare con:

```
GET /wp/v2/types
GET /wp/v2/taxonomies
```

Se emergono route custom non coperte dall'auto-discovery di default, vanno registrate esplicitamente nel client (vedi sezione 4).

### 3.7 Non fare assunzioni sull'autenticazione

Per un client di sola lettura su contenuti pubblici non serve autenticazione. Se in futuro serve accedere a contenuti privati o scrivere (POST/PUT/DELETE), il sito espone già l'endpoint per Application Passwords (visibile in `/wp-json/`), che è il meccanismo nativo consigliato da WordPress dalla versione 5.6.

### 3.8 Gestire sempre gli errori di rete e HTTP

Ogni chiamata a `wpapi` può fallire per problemi di rete, timeout, o risposte 4xx/5xx del sito. Va sempre avvolta in try/catch, senza assumere che la Promise si risolva sempre con successo.

```javascript
try {
  const posts = await site.posts().perPage(5);
} catch (err) {
  // log strutturato, retry con backoff, o fallback, a seconda del contesto
}
```

## 4. Estendere il client con route custom

Se `/wp/v2/types` o `/wp/v2/taxonomies` rivelano risorse non standard (es. un custom post type `recensioni`), vanno registrate esplicitamente, perché l'auto-discovery copre bene lo schema `wp/v2` standard ma può non mappare automaticamente ogni endpoint custom nello stesso modo comodo:

```javascript
site.recensioni = site.registerRoute('wp/v2', '/recensioni/(?P<id>)');
```

Da quel momento `site.recensioni()` si comporta come `site.posts()`, con lo stesso query builder.

## 5. Convenzioni del layer di servizio

Ogni funzione in `posts-service.js` segue queste regole:

- Ritorna sempre una query `wpapi` già filtrata sui campi minimi necessari (vedi 3.1).
- Non espone mai l'istanza `site` grezza al chiamante: il chiamante lavora solo con funzioni di dominio (`getLatestPosts`, `searchPosts`, ecc), non con la sintassi di `wpapi`.
- I parametri di paginazione (`page`, `perPage`) sono sempre espliciti e con default ragionevoli, mai impliciti.

Questo rende il codice a valle indipendente dai dettagli della libreria: se in futuro si cambia libreria client, cambia solo questo file.

## 6. Riferimenti

- Documentazione ufficiale WP REST API: https://developer.wordpress.org/rest-api/
- Reference completa degli endpoint: https://developer.wordpress.org/rest-api/reference/
- Libreria `node-wpapi`: https://github.com/WP-API/node-wpapi
- Guida di progetto (dettaglio parametri ed endpoint specifici per taxidrivers.it): `wp-rest-api-guida-taxidrivers.md`
