'use strict';

const { getSite } = require('./wp-client');

/**
 * Mapping sezioni del menu -> slug di categoria, come definito manualmente.
 * Alcuni slug sono stati corretti rispetto alla bozza originale:
 * - "streaming" -> "live-streaming-on-demand" (assumendo fosse un refuso)
 * - "approfondimento" -> "approfondimenti" (plurale, unico slug esistente)
 * - "animazione/anime" -> "anime" (gli slug WP non contengono "/")
 */
const CATEGORIES_SLUGS = {
  News: ['latest-news', 'focus-italia'],
  Recensioni: ['review', 'approfondimenti', 'live-streaming-on-demand'],
  'In Sala': ['in-sala'],
  'Cult Movies': ['cult-movie'],
  Animazione: ['animazione', 'anime'],
  'Festival di Cinema': ['festival-di-cinema'],
  Trailers: ['trailers'],
  'Serie TV': [
    'serie-tv',
    'netflix-serie-tv',
    'prime-video-serietv',
    'sky-serie-tv',
    'disney-serietv',
    'paramount-serie-tv',
    'appletv-serietv',
    'tim-vision-serie-tv',
  ],
  'Guide e Film da Vedere': ['film-da-vedere'],
  'Speciali e Magazine': ['magazine-2', 'taxidrivers-magazine'],
  'Live Streaming On Demand': ['live-streaming-on-demand'],
  Rubriche: ['rubriche'],
  Interviste: ['interviews', 'interviews-interviews'],
};

(async () => {
  try {
    const site = await getSite();

    console.log('Recupero tutte le categorie del sito per costruire la mappa slug -> id...\n');

    let page = 1;
    let allCategories = [];
    let totalPages = 1;

    do {
      const response = await site
        .categories()
        .perPage(100)
        .page(page)
        .param('_fields', 'id,slug,parent,count');

      allCategories = allCategories.concat(response);
      totalPages = response._paging ? response._paging.totalPages : 1;
      page += 1;
    } while (page <= totalPages);

    const bySlug = new Map(allCategories.map((c) => [c.slug, c]));

    console.log(`Totale categorie sul sito: ${allCategories.length}\n`);
    console.log('=== RISOLUZIONE MAPPING (slug -> id) ===\n');

    const resolved = {};
    const missing = [];

    Object.entries(CATEGORIES_SLUGS).forEach(([sectionName, slugs]) => {
      console.log(`${sectionName}:`);
      resolved[sectionName] = [];

      slugs.forEach((slug) => {
        const cat = bySlug.get(slug);
        if (!cat) {
          console.log(`  ✗ "${slug}" NON TROVATO`);
          missing.push({ section: sectionName, slug });
          return;
        }

        const hasChildren = allCategories.some((c) => c.parent === cat.id);
        console.log(
          `  ✓ "${slug}" -> id ${cat.id} (articoli diretti: ${cat.count}${hasChildren ? ', HA SOTTOCATEGORIE' : ''})`
        );
        resolved[sectionName].push({ slug, id: cat.id, hasChildren });
      });
      console.log('');
    });

    if (missing.length > 0) {
      console.log('=== ATTENZIONE: slug non trovati ===\n');
      missing.forEach((m) => console.log(`- "${m.slug}" (sezione: ${m.section})`));
      console.log('');
    }

    console.log('=== OGGETTO JS PRONTO PER posts-service.js ===\n');
    console.log(JSON.stringify(resolved, null, 2));
  } catch (err) {
    console.error('Errore durante la richiesta:', err.message);
    process.exit(1);
  }
})();