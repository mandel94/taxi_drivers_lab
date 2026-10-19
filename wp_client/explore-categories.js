'use strict';

const { getSite } = require('./wp-client');

/**
 * Ordina le categorie in una struttura ad albero basata su 'parent'.
 * Le categorie con parent = 0 sono di primo livello.
 */
function buildTree(categories) {
  const byId = new Map(categories.map((c) => [c.id, { ...c, children: [] }]));
  const roots = [];

  byId.forEach((cat) => {
    if (cat.parent && byId.has(cat.parent)) {
      byId.get(cat.parent).children.push(cat);
    } else {
      roots.push(cat);
    }
  });

  return roots;
}

function printTree(nodes, depth = 0) {
  nodes
    .sort((a, b) => b.count - a.count)
    .forEach((node) => {
      const indent = '  '.repeat(depth);
      console.log(
        `${indent}- [id: ${node.id}] ${node.name}  (slug: ${node.slug}, articoli: ${node.count})`
      );
      if (node.children.length > 0) {
        printTree(node.children, depth + 1);
      }
    });
}

(async () => {
  try {
    const site = await getSite();

    console.log('Recupero tutte le categorie (con paginazione esplicita)...\n');

    // per_page max consentito è 100. Il sito ha più di 100 categorie
    // (confermato: "Interviews" non compariva senza paginazione esplicita),
    // quindi paginiamo fino a esaurire tutti i risultati, non fidandoci
    // di un singolo perPage(100) come se fosse sempre sufficiente.
    let page = 1;
    let categories = [];
    let totalPages = 1;

    do {
      const response = await site
        .categories()
        .perPage(100)
        .page(page)
        .param('_fields', 'id,name,slug,parent,count,description');

      categories = categories.concat(response);
      totalPages = response._paging ? response._paging.totalPages : 1;
      page += 1;
    } while (page <= totalPages);

    console.log(`Totale categorie trovate: ${categories.length} (su ${totalPages} pagine)\n`);
    console.log('=== STRUTTURA GERARCHICA (ordinata per numero di articoli) ===\n');

    const tree = buildTree(categories);
    printTree(tree);

    console.log('\n=== ELENCO PIATTO (utile per copia/incolla ID) ===\n');
    categories
      .sort((a, b) => a.name.localeCompare(b.name))
      .forEach((c) => {
        console.log(`${c.id}\t${c.slug}\t${c.name}\t(parent: ${c.parent || '-'}, articoli: ${c.count})`);
      });
  } catch (err) {
    console.error('Errore durante la richiesta:', err.message);
    process.exit(1);
  }
})();