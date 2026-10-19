'use strict';

const { getSite } = require('./wp-client');

/**
 * Recupera un articolo per slug e mostra le categorie/tag effettivamente
 * assegnati, per verificare la mappatura reale tra sezioni del menu
 * (visibili nell'URL, es. /interviews/) e categorie WordPress.
 */

const SLUG = 'intervista-ad-andrea-poggio-compositore-de-linconnue';

(async () => {
  try {
    const site = await getSite();

    console.log(`Cerco l'articolo con slug: ${SLUG}\n`);

    const posts = await site
      .posts()
      .slug(SLUG)
      .embed()
      .param('_fields', 'id,title,link,slug,categories,tags,_links,_embedded');

    if (!posts || posts.length === 0) {
      console.log('Nessun articolo trovato con questo slug.');
      return;
    }

    const post = posts[0];
    console.log(`Trovato: [id: ${post.id}] ${post.title.rendered}`);
    console.log(`Link: ${post.link}\n`);

    console.log(`ID categorie assegnate: ${post.categories.join(', ') || '(nessuna)'}`);
    console.log(`ID tag assegnati: ${post.tags.join(', ') || '(nessuno)'}\n`);

    // Con _embed, i nomi delle categorie/tag sono già inclusi nella risposta,
    // evitando una seconda richiesta per risolvere gli ID in nomi leggibili.
    const embeddedTerms = post._embedded && post._embedded['wp:term'];
    if (embeddedTerms) {
      embeddedTerms.forEach((group) => {
        group.forEach((term) => {
          console.log(`- [${term.taxonomy}] ${term.name}  (id: ${term.id}, slug: ${term.slug})`);
        });
      });
    } else {
      console.log('(dati embedded non disponibili, verificare categorie/tag per ID separatamente)');
    }
  } catch (err) {
    console.error('Errore durante la richiesta:', err.message);
    process.exit(1);
  }
})();