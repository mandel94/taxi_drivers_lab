'use strict';

/**
 * Script di ingestion: popola categories_dim, articles_dim e
 * articles_categories a partire dalla WP REST API di taxidrivers.it.
 *
 * Scope di questa prima versione (ingestion base):
 *   - Solo categorie standard WordPress (namespace wp/v2/categories),
 *     nessuna tassonomia custom (da verificare separatamente via
 *     /wp/v2/taxonomies prima di estendere lo script).
 *   - Nessun popolamento di fact_wp_engagement_weekly in questo script.
 *
 * Idempotenza: tutte le scritture usano upsert (ON CONFLICT DO UPDATE),
 * quindi lo script è rieseguibile senza duplicare righe né fallire su
 * articoli/categorie già presenti. Utile sia per il primo caricamento
 * sia per run incrementali successivi.
 *
 * Modalita':
 *   - Completa (default): pagina fino a esaurimento (o MAX_PAGES).
 *     Serve per il primo caricamento o un riallineamento totale.
 *   - Incrementale (INCREMENTAL=1): scarica solo i piu' recenti e si
 *     ferma quando raggiunge articoli gia' in articles_dim. Da usare
 *     prima di 'make ingest-ga4' per coprire gli articoli pubblicati
 *     dopo l'ultima sincronizzazione, con poche richieste.
 *
 * Uso:
 *   DATABASE_URL=postgres://user:pass@localhost:5432/taxidrivers node ingest-articles.js
 *   DATABASE_URL=... INCREMENTAL=1 node ingest-articles.js
 */

const { Pool } = require('pg');
const { getSite } = require('./wp-client');
const { getCategories } = require('./posts-service');

const DATABASE_URL = process.env.DATABASE_URL;
if (!DATABASE_URL) {
  console.error('Errore: variabile d\'ambiente DATABASE_URL mancante.');
  process.exit(1);
}

const pool = new Pool({ connectionString: DATABASE_URL });

// Campi richiesti sui post per popolare articles_dim per intero.
// _embed serve solo per il featured media (url immagine in evidenza);
// l'autore lo prendiamo come ID + nome direttamente dai campi base del
// post quando disponibili, senza bisogno di _embed per quello specifico.
const ARTICLE_FIELDS = [
  'id',
  'slug',
  'link',
  'status',
  'title',
  'excerpt',
  'content',
  'author',
  'featured_media',
  'format',
  'comment_status',
  'date_gmt',
  'modified_gmt',
  'categories',
  '_links',
  '_embedded',
].join(',');

/**
 * Recupera gli articoli pubblicati, paginando fino a esaurimento (o fino
 * al limite impostato da MAX_PAGES, utile per run di test rapide senza
 * scorrere l'intero sito). Stessa logica difensiva già usata in
 * getCategories: non ci si fida di una singola pagina, si pagina sempre
 * fino a totalPages (o al limite).
 *
 * MAX_PAGES=0 o non impostata => nessun limite, run completa.
 */
async function fetchAllArticles() {
  const site = await getSite();

  const maxPages = Number(process.env.MAX_PAGES) || 0;

  let page = 1;
  let articles = [];
  let totalPages = 1;

  do {
    const response = await site
      .posts()
      .perPage(100)
      .page(page)
      .embed()
      .param('_fields', ARTICLE_FIELDS);

    articles = articles.concat(response);
    totalPages = response._paging ? response._paging.totalPages : 1;
    const effectiveTotal = maxPages > 0 ? Math.min(totalPages, maxPages) : totalPages;
    console.log(`Recuperata pagina ${page}/${effectiveTotal} (${response.length} articoli)`);
    page += 1;
  } while (page <= totalPages && (maxPages === 0 || page <= maxPages));

  if (maxPages > 0 && totalPages > maxPages) {
    console.log(
      `MAX_PAGES=${maxPages} attivo: fermato dopo ${maxPages}/${totalPages} pagine totali disponibili (run di test).`
    );
  }

  return articles;
}

/**
 * Ingestione incrementale: recupera gli articoli piu' recenti (la WP REST
 * API li ordina per data decrescente, forzato esplicitamente qui) e si
 * ferma non appena una pagina non contiene piu' article_id nuovi rispetto
 * ad articles_dim. Copre tutti gli articoli pubblicati dopo l'ultima
 * sincronizzazione con un numero minimo di richieste, senza riscaricare
 * l'intero archivio (che su questo sito supera le 500 pagine).
 *
 * MAX_PAGES resta un tetto di sicurezza opzionale sul numero di pagine.
 */
async function loadKnownArticleIds(client) {
  const { rows } = await client.query('SELECT article_id FROM articles_dim');
  return new Set(rows.map((row) => row.article_id));
}

async function fetchRecentArticles(knownIds) {
  const site = await getSite();
  const maxPages = Number(process.env.MAX_PAGES) || 0;

  let page = 1;
  let articles = [];
  let stopReason = 'caught-up';

  while (true) {
    const response = await site
      .posts()
      .perPage(100)
      .page(page)
      .embed()
      .param('orderby', 'date')
      .param('order', 'desc')
      .param('_fields', ARTICLE_FIELDS);

    const newOnPage = response.filter((post) => !knownIds.has(post.id)).length;
    console.log(
      `Recuperata pagina ${page} (${response.length} articoli, ${newOnPage} nuovi)`
    );

    if (newOnPage === 0) {
      stopReason = 'caught-up';
      break;
    }

    articles = articles.concat(response);

    if (maxPages > 0 && page >= maxPages) {
      stopReason = 'max-pages';
      break;
    }

    const totalPages = response._paging ? response._paging.totalPages : 1;
    if (page >= totalPages) {
      stopReason = 'end-of-archive';
      break;
    }

    page += 1;
  }

  console.log(
    `Ingestione incrementale terminata (${stopReason}) dopo ${page} pagine.`
  );

  return articles;
}

/**
 * Estrae l'URL del featured media dai dati _embedded, se presente.
 * Un post senza immagine in evidenza non ha wp:featuredmedia in _embedded.
 */
function extractFeaturedMediaUrl(post) {
  const media = post._embedded && post._embedded['wp:featuredmedia'];
  if (!media || !media[0] || !media[0].source_url) {
    return null;
  }
  return media[0].source_url;
}

/**
 * Estrae il nome autore dai dati _embedded, se presente.
 * Se _embed non ha risolto l'autore (raro, ma possibile in caso di
 * dati incoerenti sul sito), si ripiega su null: lo slot author_wp_id
 * resta comunque valorizzato dal campo diretto del post.
 */
function extractAuthorName(post) {
  const authors = post._embedded && post._embedded.author;
  if (!authors || !authors[0] || !authors[0].name) {
    return null;
  }
  return authors[0].name;
}

/**
 * Upsert di tutte le categorie standard WordPress in categories_dim.
 * Le categorie vanno scritte PRIMA degli articoli, perché
 * articles_categories ha una FK verso categories_dim.
 *
 * Nota sull'ordine di inserimento: la WP REST API non garantisce che le
 * categorie arrivino "genitori prima dei figli" (l'ordine dipende da
 * orderby/id, non dalla gerarchia). Con parent_id self-referenziato su
 * categories_dim, inserire una categoria figlia prima che il genitore
 * esista ancora violerebbe la FK. Per questo si procede in due passate:
 *   1) upsert di tutte le righe con parent_id lasciato NULL
 *   2) UPDATE che valorizza parent_id, quando ogni riga esiste già
 * Così il vincolo di integrità referenziale è sempre soddisfatto,
 * indipendentemente dall'ordine restituito dall'API.
 */
async function upsertCategories(client) {
  const categories = await getCategories();

  const insertQuery = `
    INSERT INTO categories_dim (category_id, parent_id, name, slug, description, wp_taxonomy, updated_at)
    VALUES ($1, NULL, $2, $3, $4, 'category', now())
    ON CONFLICT (category_id) DO UPDATE SET
      name = EXCLUDED.name,
      slug = EXCLUDED.slug,
      description = EXCLUDED.description,
      updated_at = now();
  `;

  // Prima passata: tutte le categorie esistono come riga, senza parent_id.
  for (const cat of categories) {
    await client.query(insertQuery, [cat.id, cat.name, cat.slug, cat.description || null]);
  }

  // Seconda passata: ora che ogni riga esiste, valorizza il parent_id.
  // NULLIF(parent, 0) perché WP usa 0 per "nessun genitore", non NULL.
  const updateParentQuery = `
    UPDATE categories_dim SET parent_id = NULLIF($2, 0) WHERE category_id = $1;
  `;
  for (const cat of categories) {
    await client.query(updateParentQuery, [cat.id, cat.parent || 0]);
  }

  console.log(`categories_dim: ${categories.length} categorie sincronizzate.`);
  return categories.length;
}

/**
 * Upsert di un singolo articolo in articles_dim.
 */
async function upsertArticle(client, post) {
  const upsertQuery = `
    INSERT INTO articles_dim (
      article_id, slug, link, status, title, excerpt, content_html,
      author_wp_id, author_name, featured_media_url, format, comment_status,
      published_at, modified_at, updated_at
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, now())
    ON CONFLICT (article_id) DO UPDATE SET
      slug = EXCLUDED.slug,
      link = EXCLUDED.link,
      status = EXCLUDED.status,
      title = EXCLUDED.title,
      excerpt = EXCLUDED.excerpt,
      content_html = EXCLUDED.content_html,
      author_wp_id = EXCLUDED.author_wp_id,
      author_name = EXCLUDED.author_name,
      featured_media_url = EXCLUDED.featured_media_url,
      format = EXCLUDED.format,
      comment_status = EXCLUDED.comment_status,
      published_at = EXCLUDED.published_at,
      modified_at = EXCLUDED.modified_at,
      updated_at = now();
  `;

  await client.query(upsertQuery, [
    post.id,
    post.slug,
    post.link,
    post.status,
    post.title && post.title.rendered,
    post.excerpt && post.excerpt.rendered,
    post.content && post.content.rendered,
    post.author || null,
    extractAuthorName(post),
    extractFeaturedMediaUrl(post),
    post.format || null,
    post.comment_status || null,
    post.date_gmt ? `${post.date_gmt}Z` : null,
    post.modified_gmt ? `${post.modified_gmt}Z` : null,
  ]);
}

/**
 * Sincronizza articles_categories per un articolo: cancella le
 * associazioni esistenti e reinserisce quelle correnti. Più semplice e
 * sicuro di un diff riga-per-riga, e comunque economico dato che ogni
 * articolo ha poche categorie assegnate.
 */
async function syncArticleCategories(client, articleId, categoryIds) {
  await client.query('DELETE FROM articles_categories WHERE article_id = $1', [articleId]);

  if (!categoryIds || categoryIds.length === 0) {
    return;
  }

  const values = categoryIds.map((_, i) => `($1, $${i + 2})`).join(', ');
  await client.query(
    `INSERT INTO articles_categories (article_id, category_id) VALUES ${values} ON CONFLICT DO NOTHING`,
    [articleId, ...categoryIds]
  );
}

async function run() {
  const client = await pool.connect();
  const incremental = ['1', 'true', 'yes'].includes(
    String(process.env.INCREMENTAL || '').toLowerCase()
  );

  try {
    console.log('--- Fase 1: sincronizzazione categorie ---');
    await upsertCategories(client);

    console.log(
      `\n--- Fase 2: recupero articoli da WP REST API (${incremental ? 'incrementale, solo recenti' : 'completa'}) ---`
    );
    const articles = incremental
      ? await fetchRecentArticles(await loadKnownArticleIds(client))
      : await fetchAllArticles();
    console.log(`Totale articoli recuperati: ${articles.length}`);

    if (articles.length === 0) {
      console.log('\nNessun articolo nuovo da sincronizzare: archivio gia allineato.');
      return;
    }

    console.log('\n--- Fase 3: scrittura articles_dim e articles_categories ---');
    let count = 0;
    for (const post of articles) {
      await client.query('BEGIN');
      try {
        await upsertArticle(client, post);
        await syncArticleCategories(client, post.id, post.categories || []);
        await client.query('COMMIT');
        count += 1;
        if (count % 50 === 0) {
          console.log(`Processati ${count}/${articles.length} articoli...`);
        }
      } catch (err) {
        await client.query('ROLLBACK');
        console.error(`Errore su articolo id=${post.id} (${post.slug}):`, err.message);
      }
    }

    console.log(`\nCompletato: ${count}/${articles.length} articoli scritti con successo.`);
  } finally {
    client.release();
    await pool.end();
  }
}

run().catch((err) => {
  console.error('Ingestion fallita:', err);
  process.exit(1);
});