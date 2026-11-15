'use strict';

/**
 * Riconciliazione delle categorie WordPress con categories_dim.
 *
 * Problema: categories_dim ha PK category_id e UNIQUE(slug), ma l'upsert
 * di ingest-articles.js fa ON CONFLICT (category_id). Se in WordPress una
 * categoria cambia id tenendo lo slug, l'INSERT viola UNIQUE(slug)
 * (categories_dim_slug_key) e l'ingestione si ferma.
 *
 * Soluzione in tre passi (il chiamante li esegue in un'unica transazione):
 *   1) validateWpCategories: controlla l'elenco WP prima di scrivere.
 *   2) planCategoryReconcile + applyRenames: libera gli slug in conflitto
 *      rinominando le righe del database con id diverso da quello di WP.
 *   3) applyRepoints: dopo l'upsert, sposta sull'id nuovo i legami
 *      articles_categories e i parent_id dell'id vecchio.
 * Nessuna riga di categories_dim viene mai cancellata.
 *
 * Il modulo non dipende da pg: riceve un client con il metodo query().
 */

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Valida l'elenco di categorie restituito da WordPress. Non lancia mai:
 * ritorna { valid, problems } con un messaggio in italiano per problema.
 */
function validateWpCategories(categories) {
  const problems = [];

  if (!Array.isArray(categories)) {
    return { valid: false, problems: ['l\'elenco delle categorie non e\' un array'] };
  }
  if (categories.length === 0) {
    return { valid: false, problems: ['l\'elenco delle categorie e\' vuoto'] };
  }

  const seenIds = new Set();
  const seenSlugs = new Set();

  categories.forEach((cat, index) => {
    const pos = `categoria #${index}`;
    if (!isObject(cat)) {
      problems.push(`${pos}: non e' un oggetto`);
      return;
    }

    if (!Number.isInteger(cat.id) || cat.id <= 0) {
      problems.push(`${pos}: id non valido (${String(cat.id)})`);
    } else if (seenIds.has(cat.id)) {
      problems.push(`${pos}: id duplicato (${cat.id})`);
    } else {
      seenIds.add(cat.id);
    }

    if (typeof cat.slug !== 'string' || cat.slug === '') {
      problems.push(`${pos}: slug non valido (${String(cat.slug)})`);
    } else if (seenSlugs.has(cat.slug)) {
      problems.push(`${pos}: slug duplicato (${cat.slug})`);
    } else {
      seenSlugs.add(cat.slug);
    }

    if (typeof cat.name !== 'string') {
      problems.push(`${pos}: name non valido (${String(cat.name)})`);
    }

    if (cat.parent !== undefined && cat.parent !== null
        && (!Number.isInteger(cat.parent) || cat.parent < 0)) {
      problems.push(`${pos}: parent non valido (${String(cat.parent)})`);
    }
  });

  return { valid: problems.length === 0, problems };
}

/**
 * Funzione pura: confronta le categorie WP con le righe di categories_dim
 * e ritorna { renames, replacements, orphans }, ordinati per id crescente.
 *   - renames: righe DB che occupano lo slug di una categoria WP con id
 *     diverso; vanno rinominate per liberare lo slug.
 *   - replacements: tra i renames, quelli il cui id non esiste piu' in WP
 *     (stesso slug, id nuovo): vanno ripuntati sull'id nuovo.
 *   - orphans: righe DB il cui id non e' piu' in WP e senza sostituta.
 */
function planCategoryReconcile(wpCategories, dbCategories) {
  const wpIds = new Set(wpCategories.map((c) => c.id));
  const dbBySlug = new Map(dbCategories.map((r) => [r.slug, r]));

  const renames = [];
  const replacements = [];
  const inConflict = new Set();

  for (const cat of wpCategories) {
    const row = dbBySlug.get(cat.slug);
    if (!row || row.category_id === cat.id) continue;

    const oldId = row.category_id;
    inConflict.add(oldId);

    if (wpIds.has(oldId)) {
      renames.push({
        categoryId: oldId,
        fromSlug: cat.slug,
        toSlug: `${cat.slug}--libera-${oldId}`,
      });
    } else {
      renames.push({
        categoryId: oldId,
        fromSlug: cat.slug,
        toSlug: `${cat.slug}--sostituita-${oldId}`,
      });
      replacements.push({ oldId, newId: cat.id, slug: cat.slug });
    }
  }

  const orphans = dbCategories
    .filter((r) => !wpIds.has(r.category_id) && !inConflict.has(r.category_id))
    .map((r) => ({ categoryId: r.category_id, slug: r.slug }));

  renames.sort((a, b) => a.categoryId - b.categoryId);
  replacements.sort((a, b) => a.oldId - b.oldId);
  orphans.sort((a, b) => a.categoryId - b.categoryId);

  return { renames, replacements, orphans };
}

/**
 * Libera gli slug in conflitto rinominando le righe del database.
 */
async function applyRenames(client, plan) {
  for (const r of plan.renames) {
    await client.query(
      'UPDATE categories_dim SET slug = $2 WHERE category_id = $1',
      [r.categoryId, r.toSlug]
    );
  }
}

/**
 * Per ogni sostituzione sposta sull'id nuovo i legami con gli articoli e
 * i figli dell'id vecchio. Da chiamare dopo l'upsert (l'id nuovo deve
 * esistere in categories_dim). Non cancella righe di categories_dim.
 */
async function applyRepoints(client, plan) {
  for (const r of plan.replacements) {
    await client.query(
      `INSERT INTO articles_categories (article_id, category_id)
       SELECT article_id, $2 FROM articles_categories WHERE category_id = $1
       ON CONFLICT DO NOTHING`,
      [r.oldId, r.newId]
    );
    await client.query(
      'DELETE FROM articles_categories WHERE category_id = $1',
      [r.oldId]
    );
    await client.query(
      'UPDATE categories_dim SET parent_id = $2 WHERE parent_id = $1',
      [r.oldId, r.newId]
    );
  }
}

module.exports = {
  validateWpCategories,
  planCategoryReconcile,
  applyRenames,
  applyRepoints,
};
