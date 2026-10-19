'use strict';

const { getSite } = require('./wp-client');

/**
 * Campi minimi consigliati per liste (riduce payload e tempo di risposta).
 * Aggiungere 'excerpt' o 'content' solo se effettivamente serve il testo.
 */
const LIST_FIELDS = 'id,title,link,date,slug,categories,tags';

/**
 * Mapping sezioni del menu di taxidrivers.it -> categorie WordPress.
 *
 * Ogni voce elenca gli ID di categoria che compongono quella sezione
 * editoriale (alcune sezioni corrispondono a più categorie, es. Serie TV
 * raccoglie sia la categoria padre "serie-tv" sia le sottocategorie per
 * piattaforma streaming). Il flag "includeChildren" indica se, per quella
 * specifica categoria, vanno inclusi anche gli articoli assegnati alle
 * sue sottocategorie (rilevante per "Festival di Cinema", che ha oltre
 * 140 sottocategorie, una per festival specifico).
 *
 * Verificato sul campo il 03/09/2026 con lo script resolve-category-mapping.js.
 * Se il sito aggiunge o rinomina categorie, questo mapping va rigenerato
 * (rilanciare lo script con gli slug aggiornati).
 *
 * Nota: live-streaming-on-demand (id 25048) appartiene solo alla sezione
 * "Live Streaming On Demand", non a "Recensioni", per evitare che gli
 * stessi articoli compaiano duplicati in entrambe le sezioni.
 */
const CATEGORIES = {
  News: [
    { id: 32998, includeChildren: true }, // latest-news
    { id: 32989, includeChildren: true }, // focus-italia
  ],
  Recensioni: [
    { id: 218, includeChildren: true }, // review
    { id: 25833, includeChildren: true }, // approfondimenti
  ],
  'In Sala': [{ id: 26, includeChildren: true }], // in-sala
  'Cult Movies': [{ id: 68937, includeChildren: false }], // cult-movie
  Animazione: [
    { id: 37675, includeChildren: true }, // animazione
    { id: 68908, includeChildren: false }, // anime
  ],
  'Festival di Cinema': [{ id: 20, includeChildren: true }], // festival-di-cinema
  Trailers: [{ id: 22, includeChildren: true }], // trailers
  'Serie TV': [
    { id: 29923, includeChildren: true }, // serie-tv
    { id: 33785, includeChildren: false }, // netflix-serie-tv
    { id: 33786, includeChildren: false }, // prime-video-serietv
    { id: 36480, includeChildren: false }, // sky-serie-tv
    { id: 33788, includeChildren: false }, // disney-serietv
    { id: 50587, includeChildren: false }, // paramount-serie-tv
    { id: 33787, includeChildren: false }, // appletv-serietv
    { id: 33791, includeChildren: false }, // tim-vision-serie-tv
  ],
  'Guide e Film da Vedere': [{ id: 26005, includeChildren: false }], // film-da-vedere
  'Speciali e Magazine': [
    { id: 10407, includeChildren: true }, // magazine-2
    { id: 33099, includeChildren: false }, // taxidrivers-magazine
  ],
  'Live Streaming On Demand': [{ id: 25048, includeChildren: true }], // live-streaming-on-demand
  Rubriche: [{ id: 1, includeChildren: true }], // rubriche
  Interviste: [
    { id: 32988, includeChildren: true }, // interviews
    { id: 60466, includeChildren: false }, // interviews-interviews
  ],
};

/**
 * Ultimi N articoli pubblicati, con dati collegati (autore, immagine,
 * termini di tassonomia) inclusi in un'unica risposta grazie a _embed.
 */
async function getLatestPosts(count = 10) {
  const site = await getSite();
  return site
    .posts()
    .perPage(count)
    .embed()
    .param('_fields', `${LIST_FIELDS},_links,_embedded`);
}

/**
 * Articoli di una categoria specifica, con paginazione.
 * categoryId: ID numerico della categoria (verificabile via /wp/v2/categories).
 */
async function getPostsByCategory(categoryId, { page = 1, perPage = 20 } = {}) {
  const site = await getSite();
  return site
    .posts()
    .categories(categoryId)
    .page(page)
    .perPage(perPage)
    .param('_fields', LIST_FIELDS);
}

/**
 * Articoli di una sezione editoriale del sito (es. "Recensioni", "Serie TV"),
 * risolvendo automaticamente il mapping sezione -> categorie WordPress
 * definito in CATEGORIES, incluse le sottocategorie dove necessario.
 *
 * Per le categorie con includeChildren=true, usa la sintassi a oggetto
 * del parametro categories (vedi schema WP: { terms, include_children,
 * operator }) invece del semplice array di ID, perché è l'unico modo
 * per far includere all'API anche gli articoli delle sottocategorie.
 *
 * Esempio: getPostsBySection('Serie TV', { perPage: 10 })
 */
async function getPostsBySection(sectionName, { page = 1, perPage = 20 } = {}) {
  const categoryDefs = CATEGORIES[sectionName];
  if (!categoryDefs) {
    throw new Error(
      `Sezione "${sectionName}" non riconosciuta. Sezioni disponibili: ${Object.keys(CATEGORIES).join(', ')}`
    );
  }

  const site = await getSite();

  // Se anche solo una delle categorie della sezione richiede include_children,
  // usiamo la sintassi a oggetto per l'intero set: l'API accetta un unico
  // oggetto { terms, include_children, operator } per il parametro categories,
  // quindi non è possibile mischiare una sintassi ad array semplice con una
  // a oggetto nella stessa richiesta.
  const needsIncludeChildren = categoryDefs.some((c) => c.includeChildren);
  const ids = categoryDefs.map((c) => c.id);

  const query = site.posts().page(page).perPage(perPage).param('_fields', LIST_FIELDS);

  if (needsIncludeChildren) {
    return query.param('categories', {
      terms: ids,
      include_children: true,
      operator: 'OR',
    });
  }

  return query.categories(ids);
}

/**
 * Ricerca full-text sui contenuti pubblicati.
 */
async function searchPosts(query, { perPage = 20 } = {}) {
  const site = await getSite();
  return site
    .posts()
    .search(query)
    .perPage(perPage)
    .param('_fields', LIST_FIELDS);
}

/**
 * Singolo articolo per ID, con contenuto completo e dati collegati.
 */
async function getPostById(id) {
  const site = await getSite();
  return site.posts().id(id).embed();
}

/**
 * Elenco delle categorie disponibili sul sito (utile per popolare menu
 * o mappare gli slug di navigazione a ID numerici).
 *
 * Il sito ha più di 100 categorie (verificato sul campo), quindi qui
 * pagina sempre fino a esaurimento invece di fidarsi di una singola
 * richiesta con perPage(100): affidarsi a un solo perPage(100) senza
 * paginare porta a risultati silenziosamente incompleti.
 */
async function getCategories() {
  const site = await getSite();

  let page = 1;
  let categories = [];
  let totalPages = 1;

  do {
    const response = await site
      .categories()
      .perPage(100)
      .page(page)
      .param('_fields', 'id,name,slug,parent,count');

    categories = categories.concat(response);
    totalPages = response._paging ? response._paging.totalPages : 1;
    page += 1;
  } while (page <= totalPages);

  return categories;
}

module.exports = {
  CATEGORIES,
  getLatestPosts,
  getPostsByCategory,
  getPostsBySection,
  searchPosts,
  getPostById,
  getCategories,
};