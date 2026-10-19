'use strict';

const { getSite } = require('./wp-client');

/**
 * I tag in WordPress non hanno gerarchia (a differenza delle categorie),
 * quindi qui l'elenco è piatto. Ordiniamo per numero di articoli
 * (count) per far emergere subito i tag editorialmente rilevanti
 * rispetto a quelli usati raramente.
 */

(async () => {
  try {
    const site = await getSite();

    console.log('Recupero tutti i tag (con paginazione automatica se necessario)...\n');

    let page = 1;
    let allTags = [];
    let totalPages = 1;

    do {
      const response = await site
        .tags()
        .perPage(100)
        .page(page)
        .param('_fields', 'id,name,slug,count');

      allTags = allTags.concat(response);
      totalPages = response._paging ? response._paging.totalPages : 1;
      page += 1;
    } while (page <= totalPages);

    console.log(`Totale tag trovati: ${allTags.length}\n`);

    console.log('=== TAG CON ALMENO 5 ARTICOLI (ordinati per rilevanza) ===\n');
    allTags
      .filter((t) => t.count >= 5)
      .sort((a, b) => b.count - a.count)
      .forEach((t) => {
        console.log(`[id: ${t.id}] ${t.name}  (slug: ${t.slug}, articoli: ${t.count})`);
      });

    console.log('\n=== RICERCA MIRATA: tag con nome che richiama sezioni del menu ===\n');
    const keywords = ['recension', 'serie', 'intervist', 'festival', 'magazine', 'streaming'];
    const matches = allTags.filter((t) =>
      keywords.some((kw) => t.name.toLowerCase().includes(kw) || t.slug.toLowerCase().includes(kw))
    );

    if (matches.length === 0) {
      console.log('Nessun tag trovato con questi termini chiave.');
    } else {
      matches
        .sort((a, b) => b.count - a.count)
        .forEach((t) => {
          console.log(`[id: ${t.id}] ${t.name}  (slug: ${t.slug}, articoli: ${t.count})`);
        });
    }
  } catch (err) {
    console.error('Errore durante la richiesta:', err.message);
    process.exit(1);
  }
})();