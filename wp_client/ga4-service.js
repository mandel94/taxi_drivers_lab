'use strict';

/**
 * Service layer GA4: tutte le funzioni di dominio che parlano con
 * fact_ga4_daily passano di qui, analogamente a posts-service.js per
 * il client WordPress.
 *
 * Invarianti enforced nel codice:
 *   1. La chiamata GA4 include SEMPRE 'date' tra le dimensions: una
 *      riga per giorno civile, mai un totale pre-aggregato sul periodo.
 *      Non c'e' parametro che permetta di disabilitarlo.
 *   2. Validazione riga per riga della risposta: ogni campo `date`
 *      grezzo (formato YYYYMMDD) passa per `parseGa4Date`. Le righe
 *      malformate vengono scartate e loggate (non throw, per non
 *      bloccare l'intera ingestion su una singola riga sporca).
 *   3. La funzione di scrittura e' `ingestDailyMetric(articleId,
 *      date, metricName, value)`: singolare, accetta solo una data
 *      singola. Non esiste e non viene mai aggiunta una variante che
 *      accetti un range (startDate/endDate, period, ecc.).
 *   4. Scritture idempotenti: INSERT ... ON CONFLICT (article_id,
 *      metric_date, metric_name) DO UPDATE SET metric_value =
 *      EXCLUDED.metric_value, fetched_at = EXCLUDED.fetched_at.
 */

const ALLOWED_METRICS = Object.freeze([
  'active_users',
  'screen_page_views',
  'sessions',
  'engaged_sessions',
  'engagement_rate',
  'bounce_rate',
  'average_session_duration',
  'user_engagement_duration',
]);

const GA4_METRIC_TO_COLUMN = Object.freeze({
  activeUsers: 'active_users',
  screenPageViews: 'screen_page_views',
  sessions: 'sessions',
  engagedSessions: 'engaged_sessions',
  engagementRate: 'engagement_rate',
  bounceRate: 'bounce_rate',
  averageSessionDuration: 'average_session_duration',
  userEngagementDuration: 'user_engagement_duration',
});

const UPSERT_SQL = `
  INSERT INTO fact_ga4_daily (article_id, metric_date, metric_name, metric_value, fetched_at)
  VALUES ($1, $2, $3, $4, now())
  ON CONFLICT (article_id, metric_date, metric_name) DO UPDATE SET
    metric_value = EXCLUDED.metric_value,
    fetched_at = EXCLUDED.fetched_at
`;

/**
 * Validatore: accetta solo il formato YYYYMMDD (8 cifre, anno/mese/giorno
 * coerenti con il calendario gregoriano). Ritorna la data nel formato
 * ISO YYYY-MM-DD accettato da Postgres per la colonna DATE, oppure null
 * se la stringa non rappresenta una data valida.
 *
 * Esportato per i test.
 */
function parseGa4Date(raw) {
  if (typeof raw !== 'string') return null;
  if (!/^\d{8}$/.test(raw)) return null;

  const year = Number(raw.slice(0, 4));
  const month = Number(raw.slice(4, 6));
  const day = Number(raw.slice(6, 8));

  if (year < 1900 || year > 9999) return null;
  if (month < 1 || month > 12) return null;
  if (day < 1 || day > 31) return null;

  // Round-trip: protegge da date sintatticamente valide ma impossibili
  // (es. 20260230 -> 2026-03-02). Se la Date "normalizzata" non coincide
  // con i numeri di partenza, il dato e' corrotto.
  const d = new Date(Date.UTC(year, month - 1, day));
  if (
    d.getUTCFullYear() !== year ||
    d.getUTCMonth() !== month - 1 ||
    d.getUTCDate() !== day
  ) {
    return null;
  }

  const mm = String(month).padStart(2, '0');
  const dd = String(day).padStart(2, '0');
  return `${year}-${mm}-${dd}`;
}

/**
 * Esegue una runReport GA4 con la dimensione `date` forzata tra le
 * dimensions: l'API restituisce una riga per giorno civile, che e' il
 * grain richiesto da fact_ga4_daily.
 *
 * Restituisce un array di oggetti normalizzati:
 *   { pagePath, date: 'YYYY-MM-DD', metrics: { active_users: N, ... } }
 *
 * Le righe la cui data non passa `parseGa4Date` vengono scartate e
 * loggate su `onInvalidRow` (callback opzionale, default: console.warn).
 */
async function runDailyReport(ga4Client, propertyId, {
  startDate = '7daysAgo',
  endDate = 'yesterday',
  onInvalidRow = defaultInvalidRowHandler,
} = {}) {
  if (!ga4Client) {
    throw new Error('runDailyReport: ga4Client mancante.');
  }
  if (!propertyId) {
    throw new Error('runDailyReport: propertyId mancante.');
  }

  const requestBody = {
    dimensions: [{ name: 'pagePath' }, { name: 'date' }],
    metrics: Object.keys(GA4_METRIC_TO_COLUMN).map((name) => ({ name })),
    dateRanges: [{ startDate, endDate }],
    limit: 100000,
  };

  const response = await ga4Client.runReport(propertyId, requestBody);

  const dimIndex = new Map();
  for (const h of response.dimensionHeaders || []) {
    dimIndex.set(h.name, dimIndex.size);
  }
  const metricIndex = new Map();
  for (const h of response.metricHeaders || []) {
    metricIndex.set(h.name, metricIndex.size);
  }

  const pagePathIdx = dimIndex.get('pagePath');
  const dateIdx = dimIndex.get('date');

  if (pagePathIdx === undefined || dateIdx === undefined) {
    throw new Error(
      'runDailyReport: la risposta GA4 non contiene le dimensioni attese (pagePath, date). ' +
        'Dimensioni tornate: ' +
        Array.from(dimIndex.keys()).join(', '),
    );
  }

  const out = [];
  for (const row of response.rows || []) {
    const pagePath = row.dimensionValues[pagePathIdx].value;
    const rawDate = row.dimensionValues[dateIdx].value;

    const isoDate = parseGa4Date(rawDate);
    if (!isoDate) {
      onInvalidRow({ pagePath, rawDate });
      continue;
    }

    const metrics = {};
    for (const [ga4Name, colName] of Object.entries(GA4_METRIC_TO_COLUMN)) {
      const idx = metricIndex.get(ga4Name);
      if (idx === undefined) {
        // Metrica non presente nella risposta: null, non undefined,
        // cosi' i consumer possono fare `if (value === null)` in modo
        // consistente con `value === null` per i non-finiti.
        metrics[colName] = null;
        continue;
      }
      const raw = row.metricValues[idx].value;
      const num = Number(raw);
      metrics[colName] = Number.isFinite(num) ? num : null;
    }

    out.push({ pagePath, date: isoDate, metrics });
  }

  return out;
}

function defaultInvalidRowHandler({ pagePath, rawDate }) {
  // eslint-disable-next-line no-console
  console.warn(
    `[ga4-service] Riga GA4 scartata: pagePath=${JSON.stringify(pagePath)} ` +
      `date=${JSON.stringify(rawDate)} (formato non valido, atteso YYYYMMDD).`,
  );
}

/**
 * Lookup di article_id dato un page_path. Usa una JOIN inesatta via
 * trim degli slash, come la vista fact_ga4_daily_matched definita in
 * 0002. Restituisce article_id (integer) oppure null se non risolto.
 *
 * NB: il service layer non importa nulla che sappia di routing o WP:
 * la logica di matching vive qui, il DB fa da single source of truth.
 */
async function resolveArticleIdBySlug(pgClient, pagePath) {
  if (!pagePath) return null;
  // Rimuovi prima la query string, poi gli slash iniziali/finali.
  // L'ordine e' importante: split('?') su un path con slash interni
  // (es. '/slug/') non li tocca, ma su '/slug/?utm=...' produce
  // 'slug/' e poi dobbiamo restrippare.
  const withoutQuery = String(pagePath).split('?')[0];
  const cleanSlug = withoutQuery.replace(/^\/+|\/+$/g, '');
  if (!cleanSlug) return null;

  const { rows } = await pgClient.query(
    'SELECT article_id FROM articles_dim WHERE slug = $1 LIMIT 1',
    [cleanSlug],
  );
  return rows.length > 0 ? rows[0].article_id : null;
}

/**
 * Scrittura atomica di una singola metrica giornaliera. Firma
 * strettamente singolare: accetta (articleId, date, metricName, value)
 * e NIENT'ALTRO. Non esiste una variante range-based, e non viene
 * mai aggiunta in futuro.
 *
 * `date` deve essere una stringa 'YYYY-MM-DD' (gia' validata da
 * parseGa4Date). `metricName` deve essere uno dei valori in
 * ALLOWED_METRICS. `value` deve essere un numero finito.
 *
 * La scrittura e' idempotente: ON CONFLICT aggiorna metric_value e
 * fetched_at, lasciando invariati gli altri campi della riga.
 */
async function ingestDailyMetric(pgClient, articleId, date, metricName, value) {
  _assertPgClient(pgClient);
  _assertArticleId(articleId);
  _assertDateString(date);
  _assertMetricName(metricName);
  _assertValue(value);

  await pgClient.query(UPSERT_SQL, [articleId, date, metricName, value]);
}

function _assertPgClient(client) {
  if (!client || typeof client.query !== 'function') {
    throw new Error('ingestDailyMetric: pgClient mancante o non valido.');
  }
}

function _assertArticleId(articleId) {
  if (!Number.isInteger(articleId) || articleId <= 0) {
    throw new Error(
      `ingestDailyMetric: articleId non valido (atteso intero positivo, ricevuto ${JSON.stringify(articleId)}).`,
    );
  }
}

function _assertDateString(date) {
  if (typeof date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(date)) {
    throw new Error(
      `ingestDailyMetric: date non valida (atteso 'YYYY-MM-DD', ricevuto ${JSON.stringify(date)}).`,
    );
  }
  // Non riusare parseGa4Date perche' qui il formato atteso e'
  // 'YYYY-MM-DD', non 'YYYYMMDD'. Ma la validazione di calendario
  // e' la stessa: round-trip Date -> components.
  const [y, m, d] = date.split('-').map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  if (
    dt.getUTCFullYear() !== y ||
    dt.getUTCMonth() !== m - 1 ||
    dt.getUTCDate() !== d
  ) {
    throw new Error(
      `ingestDailyMetric: date non valida come giorno di calendario (${date}).`,
    );
  }
}

function _assertMetricName(metricName) {
  if (!ALLOWED_METRICS.includes(metricName)) {
    throw new Error(
      `ingestDailyMetric: metricName non ammesso (${JSON.stringify(metricName)}). ` +
        `Atteso uno di: ${ALLOWED_METRICS.join(', ')}.`,
    );
  }
}

function _assertValue(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new Error(
      `ingestDailyMetric: value non valido (atteso numero finito, ricevuto ${JSON.stringify(value)}).`,
    );
  }
}

module.exports = {
  ALLOWED_METRICS,
  parseGa4Date,
  runDailyReport,
  resolveArticleIdBySlug,
  ingestDailyMetric,
  // Esportato per i test, non per uso esterno.
  _internal: { UPSERT_SQL },
};
