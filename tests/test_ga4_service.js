/**
 * tests/test_ga4_service.js
 *
 * Test del service layer GA4 (ga4-service.js). Usa node:test (built-in,
 * Node 18+) e un mock per il client GA4: niente OAuth, niente rete,
 * niente googleapis installato.
 *
 * Cosa verifica:
 *   - parseGa4Date: accetta solo YYYYMMDD di date valide, rifiuta tutto
 *     il resto (formato sbagliato, mese/giorno fuori range, round-trip
 *     incoerente, anno fuori [1900, 9999], non-stringa).
 *   - runDailyReport: costruisce la request con 'date' nelle
 *     dimensions (SEMPRE, nessun parametro per disabilitarlo), scarta
 *     le righe con data malformata e invoca onInvalidRow, normalizza i
 *     nomi delle metriche (camelCase -> snake_case), ritorna array
 *     con struttura { pagePath, date, metrics }.
 *   - ingestDailyMetric: firma singolare (4 parametri posizionali),
 *     valida ogni input (articleId intero positivo, date 'YYYY-MM-DD'
 *     data valida, metricName nel vocabolario, value numero finito).
 *     Esegue UPSERT_SQL con i parametri nell'ordine giusto.
 *   - resolveArticleIdBySlug: trim degli slash, query su articles_dim
 *     per slug, ritorna article_id o null.
 *
 * Esecuzione:
 *     node --test tests/test_ga4_service.js
 */

'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');

const {
  ALLOWED_METRICS,
  parseGa4Date,
  runDailyReport,
  resolveArticleIdBySlug,
  ingestDailyMetric,
} = require('../wp_client/ga4-service');

// ----------------------------------------------------------------------
// Helper: GA4 response fittizia coerente con la shape GA4 reale.
// ----------------------------------------------------------------------
function makeGa4Response(rows, dimNames = ['pagePath', 'date'], metricNames = [
  'activeUsers', 'screenPageViews', 'sessions', 'engagedSessions',
  'engagementRate', 'bounceRate', 'averageSessionDuration', 'userEngagementDuration',
]) {
  return {
    dimensionHeaders: dimNames.map((name) => ({ name })),
    metricHeaders: metricNames.map((name) => ({ name })),
    rows,
  };
}

function makeRow(pagePath, rawDate, metrics) {
  const dimValues = [{ value: pagePath }, { value: rawDate }];
  const metricValues = [
    'activeUsers', 'screenPageViews', 'sessions', 'engagedSessions',
    'engagementRate', 'bounceRate', 'averageSessionDuration', 'userEngagementDuration',
  ].map((name) => ({ value: String(metrics[name] ?? 0) }));
  return { dimensionValues: dimValues, metricValues };
}

// ----------------------------------------------------------------------
// parseGa4Date
// ----------------------------------------------------------------------
test('parseGa4Date accetta YYYYMMDD valida e ritorna YYYY-MM-DD', () => {
  assert.equal(parseGa4Date('20260908'), '2026-09-08');
  assert.equal(parseGa4Date('20240101'), '2024-01-01');
  assert.equal(parseGa4Date('20261231'), '2026-12-31');
});

test('parseGa4Date rifiuta formati non-YYYYMMDD', () => {
  assert.equal(parseGa4Date('2026-09-08'), null); // gia' separato da '-'
  assert.equal(parseGa4Date('2026090'), null);    // 7 cifre
  assert.equal(parseGa4Date('202609080'), null);  // 9 cifre
  assert.equal(parseGa4Date('abcdefgh'), null);
  assert.equal(parseGa4Date(''), null);
  assert.equal(parseGa4Date(null), null);
  assert.equal(parseGa4Date(20260908), null);     // number, non string
  assert.equal(parseGa4Date(undefined), null);
  assert.equal(parseGa4Date({}), null);
});

test('parseGa4Date rifiuta date sintatticamente valide ma impossibili (round-trip)', () => {
  // 30 febbraio: round-trip finisce in marzo
  assert.equal(parseGa4Date('20260230'), null);
  // 31 aprile
  assert.equal(parseGa4Date('20260431'), null);
  // 31 giugno
  assert.equal(parseGa4Date('20260631'), null);
});

test('parseGa4Date rifiuta anno fuori range e mese/giorno fuori range', () => {
  assert.equal(parseGa4Date('18991231'), null);  // anno < 1900
  assert.equal(parseGa4Date('10000000'), null);  // anno 10000
  assert.equal(parseGa4Date('20260000'), null);  // mese 0
  assert.equal(parseGa4Date('20261300'), null);  // mese 13
  assert.equal(parseGa4Date('20260100'), null);  // giorno 0
  assert.equal(parseGa4Date('20260132'), null);  // giorno 32
});

// ----------------------------------------------------------------------
// runDailyReport
// ----------------------------------------------------------------------
test('runDailyReport include SEMPRE "date" nelle dimensions della request', async () => {
  let capturedBody;
  const fakeClient = {
    runReport: async (_prop, body) => {
      capturedBody = body;
      return makeGa4Response([]);
    },
  };

  await runDailyReport(fakeClient, 'properties/123', {
    startDate: '7daysAgo', endDate: 'yesterday',
  });

  assert.ok(capturedBody, 'body non catturato');
  const dimNames = capturedBody.dimensions.map((d) => d.name);
  assert.deepEqual(
    dimNames.sort(),
    ['date', 'pagePath'],
    'date deve essere nelle dimensions, sempre',
  );
});

test('runDailyReport normalizza risposta: pagePath, date ISO, metrics snake_case', async () => {
  const rows = [
    makeRow('/slug1/', '20260908', {
      activeUsers: 10,
      screenPageViews: 20,
      sessions: 15,
      engagedSessions: 8,
      engagementRate: 0.5,
      bounceRate: 0.5,
      averageSessionDuration: 100,
      userEngagementDuration: 500,
    }),
  ];
  const fakeClient = { runReport: async () => makeGa4Response(rows) };

  const out = await runDailyReport(fakeClient, 'properties/123');
  assert.equal(out.length, 1);
  assert.equal(out[0].pagePath, '/slug1/');
  assert.equal(out[0].date, '2026-09-08');
  assert.equal(out[0].metrics.active_users, 10);
  assert.equal(out[0].metrics.screen_page_views, 20);
  assert.equal(out[0].metrics.sessions, 15);
  assert.equal(out[0].metrics.engaged_sessions, 8);
  assert.equal(out[0].metrics.engagement_rate, 0.5);
  assert.equal(out[0].metrics.bounce_rate, 0.5);
  assert.equal(out[0].metrics.average_session_duration, 100);
  assert.equal(out[0].metrics.user_engagement_duration, 500);
});

test('runDailyReport scarta righe con data malformata e invoca onInvalidRow', async () => {
  const rejected = [];
  const rows = [
    makeRow('/ok/', '20260908', { activeUsers: 1 }),
    makeRow('/bad-month/', '20261301', { activeUsers: 2 }),
    makeRow('/bad-format/', '2026-09-08', { activeUsers: 3 }),
    makeRow('/bad-roundtrip/', '20260230', { activeUsers: 4 }),
    makeRow('/ok2/', '20260909', { activeUsers: 5 }),
  ];
  const fakeClient = { runReport: async () => makeGa4Response(rows) };

  const out = await runDailyReport(fakeClient, 'properties/123', {
    onInvalidRow: (info) => rejected.push(info),
  });

  assert.equal(out.length, 2, 'solo 2 righe dovrebbero passare il filtro data');
  assert.deepEqual(
    out.map((r) => r.pagePath),
    ['/ok/', '/ok2/'],
  );
  assert.equal(rejected.length, 3, '3 righe malformate devono essere loggate');
  assert.equal(rejected[0].pagePath, '/bad-month/');
  assert.equal(rejected[0].rawDate, '20261301');
  assert.equal(rejected[1].rawDate, '2026-09-08');
  assert.equal(rejected[2].pagePath, '/bad-roundtrip/');
});

test('runDailyReport gestisce metriche mancanti senza throw', async () => {
  // Risposta con UNA sola metrica invece di 8: deve ritornare quella
  // e null/assente per le altre, senza esplodere.
  const rows = [
    {
      dimensionValues: [{ value: '/slug/' }, { value: '20260908' }],
      metricValues: [{ value: '7' }],
    },
  ];
  const response = {
    dimensionHeaders: [{ name: 'pagePath' }, { name: 'date' }],
    metricHeaders: [{ name: 'sessions' }],
    rows,
  };
  const fakeClient = { runReport: async () => response };

  const out = await runDailyReport(fakeClient, 'properties/123');
  assert.equal(out.length, 1);
  assert.equal(out[0].metrics.sessions, 7);
  assert.equal(out[0].metrics.active_users, null);
});

test('runDailyReport rifiuta se la risposta manca di pagePath/date', async () => {
  const fakeClient = {
    runReport: async () => ({
      dimensionHeaders: [{ name: 'pagePath' }],  // manca 'date'
      metricHeaders: [],
      rows: [],
    }),
  };
  await assert.rejects(
    () => runDailyReport(fakeClient, 'properties/123'),
    /non contiene le dimensioni attese/,
  );
});

// ----------------------------------------------------------------------
// ingestDailyMetric - firma singolare, validazioni, UPSERT
// ----------------------------------------------------------------------
test('ingestDailyMetric esegue UPSERT con i parametri nell ordine giusto', async () => {
  const calls = [];
  const fakePg = {
    query: async (sql, params) => {
      calls.push({ sql: sql.trim(), params });
      return { rowCount: 1, rows: [] };
    },
  };

  await ingestDailyMetric(fakePg, 1001, '2026-09-08', 'active_users', 42);

  assert.equal(calls.length, 1);
  const { sql, params } = calls[0];
  assert.match(sql, /INSERT INTO fact_ga4_daily/i);
  assert.match(sql, /ON CONFLICT \(article_id, metric_date, metric_name\)/);
  assert.match(sql, /DO UPDATE SET/);
  assert.match(sql, /metric_value = EXCLUDED\.metric_value/);
  assert.match(sql, /fetched_at = EXCLUDED\.fetched_at/);
  assert.deepEqual(params, [1001, '2026-09-08', 'active_users', 42]);
});

test('ingestDailyMetric rifiuta articleId non valido', async () => {
  const fakePg = { query: async () => ({ rowCount: 0, rows: [] }) };
  await assert.rejects(() => ingestDailyMetric(fakePg, 0, '2026-09-08', 'active_users', 1), /articleId/);
  await assert.rejects(() => ingestDailyMetric(fakePg, -5, '2026-09-08', 'active_users', 1), /articleId/);
  await assert.rejects(() => ingestDailyMetric(fakePg, 1.5, '2026-09-08', 'active_users', 1), /articleId/);
  await assert.rejects(() => ingestDailyMetric(fakePg, '1001', '2026-09-08', 'active_users', 1), /articleId/);
  await assert.rejects(() => ingestDailyMetric(fakePg, null, '2026-09-08', 'active_users', 1), /articleId/);
});

test('ingestDailyMetric rifiuta date non in formato YYYY-MM-DD', async () => {
  const fakePg = { query: async () => ({ rowCount: 0, rows: [] }) };
  await assert.rejects(() => ingestDailyMetric(fakePg, 1, '20260908', 'active_users', 1), /date/);  // YYYYMMDD
  await assert.rejects(() => ingestDailyMetric(fakePg, 1, '2026-9-8', 'active_users', 1), /date/);   // non zero-padded
  await assert.rejects(() => ingestDailyMetric(fakePg, 1, '2026-13-01', 'active_users', 1), /date/); // mese invalido
  await assert.rejects(() => ingestDailyMetric(fakePg, 1, '2026-02-30', 'active_users', 1), /date/); // round-trip
  await assert.rejects(() => ingestDailyMetric(fakePg, 1, null, 'active_users', 1), /date/);
  await assert.rejects(() => ingestDailyMetric(fakePg, 1, 20260908, 'active_users', 1), /date/);
});

test('ingestDailyMetric rifiuta metricName fuori vocabolario', async () => {
  const fakePg = { query: async () => ({ rowCount: 0, rows: [] }) };
  await assert.rejects(
    () => ingestDailyMetric(fakePg, 1, '2026-09-08', 'inventata', 1),
    /metricName non ammesso/,
  );
  await assert.rejects(
    () => ingestDailyMetric(fakePg, 1, '2026-09-08', '', 1),
    /metricName non ammesso/,
  );
});

test('ingestDailyMetric rifiuta value non finito', async () => {
  const fakePg = { query: async () => ({ rowCount: 0, rows: [] }) };
  await assert.rejects(
    () => ingestDailyMetric(fakePg, 1, '2026-09-08', 'active_users', Infinity),
    /value/,
  );
  await assert.rejects(
    () => ingestDailyMetric(fakePg, 1, '2026-09-08', 'active_users', NaN),
    /value/,
  );
  await assert.rejects(
    () => ingestDailyMetric(fakePg, 1, '2026-09-08', 'active_users', '10'),
    /value/,
  );
  await assert.rejects(
    () => ingestDailyMetric(fakePg, 1, '2026-09-08', 'active_users', null),
    /value/,
  );
});

test('ingestDailyMetric rifiuta pgClient mancante o non valido', async () => {
  await assert.rejects(() => ingestDailyMetric(null, 1, '2026-09-08', 'active_users', 1), /pgClient/);
  await assert.rejects(() => ingestDailyMetric({}, 1, '2026-09-08', 'active_users', 1), /pgClient/);
});

test('ingestDailyMetric accetta tutti i valori del vocabolario', async () => {
  const fakePg = { query: async () => ({ rowCount: 1, rows: [] }) };
  for (const m of ALLOWED_METRICS) {
    await ingestDailyMetric(fakePg, 1, '2026-09-08', m, 0);
  }
});

// ----------------------------------------------------------------------
// resolveArticleIdBySlug
// ----------------------------------------------------------------------
test('resolveArticleIdBySlug ritorna article_id su match', async () => {
  const fakePg = {
    query: async (sql, params) => {
      assert.match(sql, /FROM articles_dim/);
      assert.match(sql, /WHERE slug = \$1/);
      assert.equal(params[0], 'slug1');
      return { rows: [{ article_id: 1001 }] };
    },
  };
  assert.equal(await resolveArticleIdBySlug(fakePg, '/slug1/'), 1001);
});

test('resolveArticleIdBySlug normalizza pagePath (trim slash, no query string)', async () => {
  const capturedParams = [];
  const fakePg = {
    query: async (_sql, params) => {
      capturedParams.push(params[0]);
      return { rows: [] };
    },
  };
  await resolveArticleIdBySlug(fakePg, '///slug1///');
  await resolveArticleIdBySlug(fakePg, '/slug1/?utm=foo');
  await resolveArticleIdBySlug(fakePg, 'slug1');
  assert.deepEqual(capturedParams, ['slug1', 'slug1', 'slug1']);
});

test('resolveArticleIdBySlug ritorna null su no-match', async () => {
  const fakePg = { query: async () => ({ rows: [] }) };
  assert.equal(await resolveArticleIdBySlug(fakePg, '/non-esiste/'), null);
});

test('resolveArticleIdBySlug ritorna null per pagePath vuoto / solo slash', async () => {
  const fakePg = { query: async () => { throw new Error('non dovrebbe query-are'); } };
  assert.equal(await resolveArticleIdBySlug(fakePg, ''), null);
  assert.equal(await resolveArticleIdBySlug(fakePg, null), null);
  assert.equal(await resolveArticleIdBySlug(fakePg, '///'), null);
  assert.equal(await resolveArticleIdBySlug(fakePg, '/?'), null);
});

// ----------------------------------------------------------------------
// Anti-regressione: la firma di ingestDailyMetric e' singolare,
// non esiste e non deve esistere una variante che accetti range.
// ----------------------------------------------------------------------
test('ingestDailyMetric non accetta un sesto parametro come range', () => {
  // La firma canonica e' (pgClient, articleId, date, metricName, value)
  // = 5 parametri posizionali, tutti obbligatori. Se in futuro qualcuno
  // aggiungesse un sesto parametro (es. startDate, endDate, period), il
  // .length cambierebbe e questo test fallirebbe.
  assert.equal(
    ingestDailyMetric.length,
    5,
    'firma deve essere (pgClient, articleId, date, metricName, value) = 5 params, ' +
      'no range/period/extra parametri',
  );
});
