'use strict';

const { getPostsBySection, CATEGORIES } = require('./posts-service');

/**
 * Verifica rapida: per ogni sezione del mapping, recupera i primi 3
 * articoli e stampa titolo + categorie assegnate, per controllo visivo
 * che il filtro (incluso include_children dove previsto) funzioni.
 */

(async () => {
  const sections = Object.keys(CATEGORIES);

  for (const section of sections) {
    console.log(`\n=== ${section} ===`);
    try {
      const posts = await getPostsBySection(section, { perPage: 3 });
      if (posts.length === 0) {
        console.log('  (nessun articolo trovato)');
        continue;
      }
      posts.forEach((p) => {
        console.log(`  - [cat: ${p.categories.join(',')}] ${p.title.rendered}`);
      });
    } catch (err) {
      console.log(`  ERRORE: ${err.message}`);
    }
  }
})();