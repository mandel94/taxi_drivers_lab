/**
 * tests/test_category_reconcile.js
 *
 * Test del modulo di riconciliazione delle categorie WordPress con
 * categories_dim (category-reconcile.js). Usa node:test (built-in,
 * Node 18+) e un client finto che registra le query: niente rete,
 * niente database.
 *
 * Contesto: categories_dim ha PK category_id e UNIQUE(slug), ma l'upsert
 * e' ON CONFLICT (category_id). Se in WordPress una categoria cambia id
 * tenendo lo slug, l'INSERT viola UNIQUE(slug) (categories_dim_slug_key)
 * e l'ingestione si ferma.
 *
 * Cosa verifica:
 *   - validateWpCategories: non lancia mai; valid=false con messaggi in
 *     problems per input non array, array vuoto, elementi non oggetto,
 *     id non intero positivo, slug non stringa non vuota, name non
 *     stringa, parent non intero >= 0 (assente ammesso), id duplicati,
 *     slug duplicati; valid=true altrimenti.
 *   - planCategoryReconcile: funzione pura che produce renames (libera
 *     lo slug con suffisso '--sostituita-M' o '--libera-M'),
 *     replacements (id vecchio sparito, stesso slug su id nuovo) e
 *     orphans (righe sparite senza sostituta), ordinati per id
 *     crescente; nessun conflitto, slug scambiati, categorie nuove,
 *     idempotenza dopo l'applicazione del piano.
 *   - applyRenames / applyRepoints: query attese, params e ordine; nessuna
 *     query a piano vuoto; mai DELETE FROM categories_dim; gli errori di
 *     client.query vengono propagati.
 *
 * Esecuzione:
 *     node --test tests/test_category_reconcile.js
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');

const {
  validateWpCategories,
  planCategoryReconcile,
  applyRenames,
  applyRepoints,
} = require('../wp_client/category-reconcile');

// ----------------------------------------------------------------------
// Helper
// ----------------------------------------------------------------------
function makeClient(failWith = null) {
  const calls = [];
  return {
    calls,
    async query(text, params) {
      calls.push({ text, params });
      if (failWith) throw failWith;
      return { rows: [], rowCount: 0 };
    },
  };
}

function wp(id, slug, parent = 0, name = `Cat ${id}`) {
  return { id, slug, name, parent };
}

function db(categoryId, slug) {
  return { category_id: categoryId, slug };
}

function validOne() {
  return { id: 10, slug: 'cinema', name: 'Cinema', parent: 0 };
}

function assertInvalid(input) {
  let result;
  assert.doesNotThrow(() => {
    result = validateWpCategories(input);
  });
  assert.equal(result.valid, false);
  assert.ok(Array.isArray(result.problems));
  assert.ok(result.problems.length >= 1, 'almeno un messaggio in problems');
  for (const p of result.problems) assert.equal(typeof p, 'string');
}

const EMPTY_PLAN = { renames: [], replacements: [], orphans: [] };

// ----------------------------------------------------------------------
// validateWpCategories
// ----------------------------------------------------------------------
test('validateWpCategories accetta un elenco valido', () => {
  const result = validateWpCategories([
    { id: 1, slug: 'cinema', name: 'Cinema', parent: 0 },
    { id: 2, slug: 'serie-tv', name: 'Serie TV', parent: 1 },
  ]);
  assert.deepEqual(result, { valid: true, problems: [] });
});

test('validateWpCategories rifiuta un array vuoto', () => {
  assertInvalid([]);
});

test('validateWpCategories rifiuta input che non e un array (null, oggetto, stringa)', () => {
  assertInvalid(null);
  assertInvalid({ id: 1, slug: 'a', name: 'A', parent: 0 });
  assertInvalid('categorie');
});

test('validateWpCategories rifiuta id null (errore reale del 10/11: null value in column category_id)', () => {
  assertInvalid([{ ...validOne(), id: null }]);
});

test('validateWpCategories rifiuta id stringa', () => {
  assertInvalid([{ ...validOne(), id: '10' }]);
});

test('validateWpCategories rifiuta id 0, negativo o assente', () => {
  assertInvalid([{ ...validOne(), id: 0 }]);
  assertInvalid([{ ...validOne(), id: -5 }]);
  const { id, ...senzaId } = validOne();
  assertInvalid([senzaId]);
});

test('validateWpCategories rifiuta slug vuoto', () => {
  assertInvalid([{ ...validOne(), slug: '' }]);
});

test('validateWpCategories rifiuta slug mancante', () => {
  const { slug, ...senzaSlug } = validOne();
  assertInvalid([senzaSlug]);
});

test('validateWpCategories rifiuta name mancante', () => {
  const { name, ...senzaName } = validOne();
  assertInvalid([senzaName]);
});

test('validateWpCategories rifiuta parent negativo', () => {
  assertInvalid([{ ...validOne(), parent: -1 }]);
});

test('validateWpCategories ammette parent assente o undefined (vale 0)', () => {
  const { parent, ...senzaParent } = validOne();
  assert.deepEqual(validateWpCategories([senzaParent]), { valid: true, problems: [] });
  assert.deepEqual(
    validateWpCategories([{ ...validOne(), parent: undefined }]),
    { valid: true, problems: [] },
  );
});

test('validateWpCategories rifiuta id duplicati', () => {
  assertInvalid([
    { id: 1, slug: 'a', name: 'A', parent: 0 },
    { id: 1, slug: 'b', name: 'B', parent: 0 },
  ]);
});

test('validateWpCategories rifiuta slug duplicati', () => {
  assertInvalid([
    { id: 1, slug: 'a', name: 'A', parent: 0 },
    { id: 2, slug: 'a', name: 'B', parent: 0 },
  ]);
});

test('validateWpCategories rifiuta un elemento non oggetto (null dentro l array)', () => {
  assertInvalid([validOne(), null]);
});

// ----------------------------------------------------------------------
// planCategoryReconcile
// ----------------------------------------------------------------------
test('planCategoryReconcile senza conflitti ritorna un piano vuoto', () => {
  const plan = planCategoryReconcile(
    [wp(1, 'a'), wp(2, 'b')],
    [db(1, 'a'), db(2, 'b')],
  );
  assert.deepEqual(plan, EMPTY_PLAN);
});

test('planCategoryReconcile gestisce la sostituzione semplice (stesso slug su id nuovo)', () => {
  const plan = planCategoryReconcile(
    [wp(72596, '3-serie-tv-da-vedere-adesso')],
    [db(72613, '3-serie-tv-da-vedere-adesso')],
  );
  assert.deepEqual(plan.renames, [
    {
      categoryId: 72613,
      fromSlug: '3-serie-tv-da-vedere-adesso',
      toSlug: '3-serie-tv-da-vedere-adesso--sostituita-72613',
    },
  ]);
  assert.deepEqual(plan.replacements, [
    { oldId: 72613, newId: 72596, slug: '3-serie-tv-da-vedere-adesso' },
  ]);
  assert.deepEqual(plan.orphans, []);
});

test('planCategoryReconcile gestisce i tre casi reali insieme, ordinati per id crescente', () => {
  // Messi volutamente in disordine in input.
  const wpCats = [
    wp(72596, '3-serie-tv-da-vedere-adesso'),
    wp(72646, 'matera-film-festival'),
    wp(72607, 'festival-di-roma'),
  ];
  const dbCats = [
    db(72650, 'matera-film-festival'),
    db(72613, '3-serie-tv-da-vedere-adesso'),
    db(72611, 'festival-di-roma'),
  ];
  const plan = planCategoryReconcile(wpCats, dbCats);

  assert.deepEqual(plan.renames, [
    { categoryId: 72611, fromSlug: 'festival-di-roma', toSlug: 'festival-di-roma--sostituita-72611' },
    {
      categoryId: 72613,
      fromSlug: '3-serie-tv-da-vedere-adesso',
      toSlug: '3-serie-tv-da-vedere-adesso--sostituita-72613',
    },
    {
      categoryId: 72650,
      fromSlug: 'matera-film-festival',
      toSlug: 'matera-film-festival--sostituita-72650',
    },
  ]);
  assert.deepEqual(plan.replacements, [
    { oldId: 72611, newId: 72607, slug: 'festival-di-roma' },
    { oldId: 72613, newId: 72596, slug: '3-serie-tv-da-vedere-adesso' },
    { oldId: 72650, newId: 72646, slug: 'matera-film-festival' },
  ]);
  assert.deepEqual(plan.orphans, []);
});

test('planCategoryReconcile segnala come orfana una categoria cancellata senza sostituta', () => {
  const plan = planCategoryReconcile(
    [wp(1, 'a')],
    [db(1, 'a'), db(9, 'cancellata')],
  );
  assert.deepEqual(plan.renames, []);
  assert.deepEqual(plan.replacements, []);
  assert.deepEqual(plan.orphans, [{ categoryId: 9, slug: 'cancellata' }]);
});

test('planCategoryReconcile ordina gli orfani per id crescente', () => {
  const plan = planCategoryReconcile(
    [wp(1, 'a')],
    [db(30, 'z'), db(1, 'a'), db(20, 'y')],
  );
  assert.deepEqual(plan.orphans, [
    { categoryId: 20, slug: 'y' },
    { categoryId: 30, slug: 'z' },
  ]);
});

test('planCategoryReconcile gestisce slug scambiati tra due id presenti in entrambi', () => {
  const plan = planCategoryReconcile(
    [wp(1, 'b'), wp(2, 'a')],
    [db(1, 'a'), db(2, 'b')],
  );
  assert.deepEqual(plan.renames, [
    { categoryId: 1, fromSlug: 'a', toSlug: 'a--libera-1' },
    { categoryId: 2, fromSlug: 'b', toSlug: 'b--libera-2' },
  ]);
  assert.deepEqual(plan.replacements, []);
  assert.deepEqual(plan.orphans, []);
});

test('planCategoryReconcile ignora una categoria nuova in WordPress senza riga nel database', () => {
  const plan = planCategoryReconcile(
    [wp(1, 'a'), wp(2, 'nuova')],
    [db(1, 'a')],
  );
  assert.deepEqual(plan, EMPTY_PLAN);
});

test('planCategoryReconcile non vede conflitto con stesso id e stesso slug', () => {
  const plan = planCategoryReconcile([wp(5, 'stessa')], [db(5, 'stessa')]);
  assert.deepEqual(plan, EMPTY_PLAN);
});

test('planCategoryReconcile e una funzione pura: non modifica gli argomenti', () => {
  const wpCats = [wp(72596, 'x'), wp(2, 'a'), wp(1, 'b')];
  const dbCats = [db(72613, 'x'), db(1, 'a'), db(2, 'b'), db(99, 'sparita')];
  const wpCopy = structuredClone(wpCats);
  const dbCopy = structuredClone(dbCats);

  planCategoryReconcile(wpCats, dbCats);

  assert.deepEqual(wpCats, wpCopy);
  assert.deepEqual(dbCats, dbCopy);
});

test('planCategoryReconcile e idempotente: dopo aver applicato il piano non restano conflitti', () => {
  const wpCats = [
    wp(72596, '3-serie-tv-da-vedere-adesso'),
    wp(72607, 'festival-di-roma'),
    wp(1, 'b'),
    wp(2, 'a'),
    wp(50, 'nuova'),
  ];
  const dbCats = [
    db(72613, '3-serie-tv-da-vedere-adesso'),
    db(72611, 'festival-di-roma'),
    db(1, 'a'),
    db(2, 'b'),
    db(99, 'sparita'),
  ];

  const plan = planCategoryReconcile(wpCats, dbCats);
  assert.ok(plan.renames.length > 0, 'il primo piano deve avere dei rename');

  // Simula le query: rinomina gli slug...
  const simulated = dbCats.map((r) => ({ ...r }));
  for (const r of plan.renames) {
    const row = simulated.find((x) => x.category_id === r.categoryId);
    row.slug = r.toSlug;
  }
  // ...poi l'upsert ON CONFLICT (category_id): aggiorna o inserisce.
  for (const c of wpCats) {
    const row = simulated.find((x) => x.category_id === c.id);
    if (row) row.slug = c.slug;
    else simulated.push({ category_id: c.id, slug: c.slug });
  }

  const second = planCategoryReconcile(wpCats, simulated);
  assert.deepEqual(second.renames, []);
  assert.deepEqual(second.replacements, []);
});

// ----------------------------------------------------------------------
// applyRenames
// ----------------------------------------------------------------------
test('applyRenames con piano vuoto non esegue query', async () => {
  const client = makeClient();
  await applyRenames(client, EMPTY_PLAN);
  assert.equal(client.calls.length, 0);
});

test('applyRenames esegue una UPDATE per voce, con params giusti e nell ordine del piano', async () => {
  const client = makeClient();
  const plan = {
    renames: [
      { categoryId: 72611, fromSlug: 'festival-di-roma', toSlug: 'festival-di-roma--sostituita-72611' },
      { categoryId: 72650, fromSlug: 'matera-film-festival', toSlug: 'matera-film-festival--sostituita-72650' },
    ],
    replacements: [],
    orphans: [],
  };
  await applyRenames(client, plan);

  assert.equal(client.calls.length, 2);
  for (const call of client.calls) {
    assert.match(call.text, /UPDATE\s+categories_dim\s+SET\s+slug\s*=\s*\$2\s+WHERE\s+category_id\s*=\s*\$1/i);
  }
  assert.deepEqual(client.calls[0].params, [72611, 'festival-di-roma--sostituita-72611']);
  assert.deepEqual(client.calls[1].params, [72650, 'matera-film-festival--sostituita-72650']);
});

test('applyRenames propaga l errore di client.query senza inghiottirlo', async () => {
  const boom = new Error('boom rename');
  const client = makeClient(boom);
  const plan = {
    renames: [{ categoryId: 1, fromSlug: 'a', toSlug: 'a--libera-1' }],
    replacements: [],
    orphans: [],
  };
  await assert.rejects(applyRenames(client, plan), (err) => err === boom);
});

// ----------------------------------------------------------------------
// applyRepoints
// ----------------------------------------------------------------------
test('applyRepoints con piano vuoto non esegue query', async () => {
  const client = makeClient();
  await applyRepoints(client, EMPTY_PLAN);
  assert.equal(client.calls.length, 0);
});

test('applyRepoints con una sostituzione esegue 3 query nell ordine insert, delete, update parent', async () => {
  const client = makeClient();
  const plan = {
    renames: [],
    replacements: [{ oldId: 72613, newId: 72596, slug: '3-serie-tv-da-vedere-adesso' }],
    orphans: [],
  };
  await applyRepoints(client, plan);

  assert.equal(client.calls.length, 3);

  const [a, b, c] = client.calls;
  assert.match(a.text, /INSERT\s+INTO\s+articles_categories/i);
  assert.match(a.text, /ON\s+CONFLICT\s+DO\s+NOTHING/i);
  assert.deepEqual(a.params, [72613, 72596]);

  assert.match(b.text, /DELETE\s+FROM\s+articles_categories/i);
  assert.match(b.text, /WHERE\s+category_id\s*=\s*\$1/i);
  assert.deepEqual(b.params, [72613]);

  assert.match(c.text, /UPDATE\s+categories_dim\s+SET\s+parent_id/i);
  assert.match(c.text, /parent_id\s*=\s*\$2\s+WHERE\s+parent_id\s*=\s*\$1/i);
  assert.deepEqual(c.params, [72613, 72596]);
});

test('applyRepoints con due sostituzioni esegue 6 query raggruppate per sostituzione', async () => {
  const client = makeClient();
  const plan = {
    renames: [],
    replacements: [
      { oldId: 72611, newId: 72607, slug: 'festival-di-roma' },
      { oldId: 72650, newId: 72646, slug: 'matera-film-festival' },
    ],
    orphans: [],
  };
  await applyRepoints(client, plan);

  assert.equal(client.calls.length, 6);
  const kinds = client.calls.map((c) => {
    if (/INSERT\s+INTO\s+articles_categories/i.test(c.text)) return 'insert';
    if (/DELETE\s+FROM\s+articles_categories/i.test(c.text)) return 'delete';
    if (/UPDATE\s+categories_dim\s+SET\s+parent_id/i.test(c.text)) return 'parent';
    return 'altro';
  });
  assert.deepEqual(kinds, ['insert', 'delete', 'parent', 'insert', 'delete', 'parent']);

  assert.deepEqual(client.calls[0].params, [72611, 72607]);
  assert.deepEqual(client.calls[1].params, [72611]);
  assert.deepEqual(client.calls[2].params, [72611, 72607]);
  assert.deepEqual(client.calls[3].params, [72650, 72646]);
  assert.deepEqual(client.calls[4].params, [72650]);
  assert.deepEqual(client.calls[5].params, [72650, 72646]);
});

test('applyRenames e applyRepoints non eseguono mai DELETE FROM categories_dim', async () => {
  const client = makeClient();
  const plan = {
    renames: [{ categoryId: 72613, fromSlug: 's', toSlug: 's--sostituita-72613' }],
    replacements: [{ oldId: 72613, newId: 72596, slug: 's' }],
    orphans: [{ categoryId: 9, slug: 'cancellata' }],
  };
  await applyRenames(client, plan);
  await applyRepoints(client, plan);

  assert.ok(client.calls.length > 0);
  for (const call of client.calls) {
    assert.doesNotMatch(call.text, /DELETE\s+FROM\s+categories_dim/i);
  }
});

test('applyRepoints propaga l errore di client.query senza inghiottirlo', async () => {
  const boom = new Error('boom repoint');
  const client = makeClient(boom);
  const plan = {
    renames: [],
    replacements: [{ oldId: 1, newId: 2, slug: 'a' }],
    orphans: [],
  };
  await assert.rejects(applyRepoints(client, plan), (err) => err === boom);
});
