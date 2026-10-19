'use strict';

const { getSite } = require('./wp-client');

(async () => {
  try {
    const site = await getSite();

    console.log('=== TIPI DI CONTENUTO (/wp/v2/types) ===\n');
    const types = await site.types();
    Object.entries(types).forEach(([slug, def]) => {
      console.log(`- ${slug}`);
      console.log(`  nome: ${def.name}`);
      console.log(`  rest_base: ${def.rest_base || '(non impostato, probabilmente = slug)'}`);
      console.log(`  descrizione: ${def.description || '(nessuna)'}`);
      console.log('');
    });

    console.log('\n=== TASSONOMIE (/wp/v2/taxonomies) ===\n');
    const taxonomies = await site.taxonomies();
    Object.entries(taxonomies).forEach(([slug, def]) => {
      console.log(`- ${slug}`);
      console.log(`  nome: ${def.name}`);
      console.log(`  rest_base: ${def.rest_base || '(non impostato, probabilmente = slug)'}`);
      console.log(`  tipi associati: ${(def.types || []).join(', ') || '(nessuno)'}`);
      console.log('');
    });
  } catch (err) {
    console.error('Errore durante la richiesta:', err.message);
    process.exit(1);
  }
})();