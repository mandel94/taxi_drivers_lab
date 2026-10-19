'use strict';

/**
 * Script di ingestion GA4 -> fact_ga4_daily.
 *
 * Orchestrazione:
 *   1. Carica la property GA4 da process.env.GA4_PROPERTY_ID.
 *   2. Per ogni articolo presente in articles_dim (con slug non nullo),
 *      interroga runDailyReport sul page_path corrispondente.
 *   3. Per ogni response row, risolve l'article_id via slug (DB single
 *      source of truth, NON usa la risposta come cache).
 *   4. Per ogni metrica, chiama ingestDailyMetric: scrittura singolare,
 *      idempotente, ON CONFLICT DO UPDATE.
 *
 * Tutta la logica di business (validazione date, query GA4, upsert)
 * vive in ga4-service.js / ga4-client.js, mai qui dentro.
 *
 * Idempotenza end-to-end: rilanciare lo script sullo stesso range NON
 * duplica righe e aggiorna solo fetched_at + metric_value.
 *
 * Uso:
 *   DATABASE_URL=postgres://user:pass@localhost:5432/taxidrivers \
 *   GA4_PROPERTY_ID=394327334 \
 *   node ingest-ga4.js --start 7daysAgo --end yesterday
 */

const { Pool } = require('pg');
const { GA4Client } = require('./ga4-client');
const {
  runDailyReport,
  resolveArticleIdBySlug,
  ingestDailyMetric,
  ALLOWED_METRICS,
} = require('./ga4-service');

const DATABASE_URL = process.env.DATABASE_URL;
if (!DATABASE_URL) {
  console.error("Errore: variabile d'ambiente DATABASE_URL mancante.");
  process.exit(1);
}
const GA4_PROPERTY_ID = process.env.GA4_PROPERTY_ID;
if (!GA4_PROPERTY_ID) {
  console.error("Errore: variabile d'ambiente GA4_PROPERTY_ID mancante.");
  process.exit(1);
}

const pool = new Pool({ connectionString: DATABASE_URL });

/**
 * Recupera gli articoli da articles_dim con slug valorizzato.
 * Solo gli articoli con slug possono essere risolti a partire da un
 * page_path GA4, quindi gli altri non hanno senso per questa ingestion.
 */
async function loadArticlesWithSlug(client) {
  const { rows } = await client.query(
    'SELECT article_id, slug FROM articles_dim WHERE slug IS NOT NULL ORDER BY article_id',
  );
  return rows;
}

/**
 * Ingestion per un singolo articolo.
 * Restituisce un contatore per articolo: scritti/aggiornati/scartati.
 */
async function ingestForArticle(client, ga4Client, article, { startDate, endDate }) {
  const pagePath = `/${article.slug}/`;
  const rows = await runDailyReport(ga4Client, GA4_PROPERTY_ID, {
    startDate,
    endDate,
  });

  let written = 0;
  let rejected = 0;

  for (const row of rows) {
    // runDailyReport gia' filtra le date malformate. Qui filtriamo solo
    // le righe che non corrispondono al pagePath dell'articolo che
    // stiamo processando (filtro difensivo: GA4 puo' restituire pagine
    // extra se il filtro lato API non e' abbastanza stretto).
    if (row.pagePath !== pagePath) continue;

    for (const metricName of ALLOWED_METRICS) {
      const value = row.metrics[metricName];
      if (value === null || value === undefined) continue;
      try {
        await ingestDailyMetric(
          client,
          article.article_id,
          row.date,
          metricName,
          value,
        );
        written += 1;
      } catch (err) {
        // Non bloccare l'intera ingestion su un singolo errore di riga.
        // Tipici: FK violation se article_id sparisce tra il SELECT e
        // l'INSERT, oppure CHECK violation su metric_name (non dovrebbe
        // accadere qui, ma meglio non assumere).
        console.error(
          `[ingest-ga4] article_id=${article.article_id} ` +
            `date=${row.date} metric=${metricName}: ${err.message}`,
        );
        rejected += 1;
      }
    }
  }

  return { written, rejected };
}

async function run() {
  const args = parseArgs(process.argv.slice(2));
  const { startDate, endDate } = args;

  const ga4Client = new GA4Client();
  const client = await pool.connect();

  try {
    console.log('--- Fase 1: caricamento articoli da articles_dim ---');
    const articles = await loadArticlesWithSlug(client);
    console.log(`Articoli con slug: ${articles.length}`);

    console.log(
      `\n--- Fase 2: ingestion GA4 (${startDate} -> ${endDate}) ---\n`,
    );

    let totalWritten = 0;
    let totalRejected = 0;
    let processed = 0;

    for (const article of articles) {
      const { written, rejected } = await ingestForArticle(
        client,
        ga4Client,
        article,
        { startDate, endDate },
      );
      totalWritten += written;
      totalRejected += rejected;
      processed += 1;

      if (processed % 50 === 0 || written > 0) {
        console.log(
          `[${processed}/${articles.length}] article_id=${article.article_id} ` +
            `slug=${article.slug}: scritti=${written} scartati=${rejected}`,
        );
      }
    }

    console.log(
      `\nCompletato. Articoli processati=${processed}, ` +
        `righe scritte=${totalWritten}, righe scartate=${totalRejected}.`,
    );
  } finally {
    client.release();
    await pool.end();
  }
}

function parseArgs(argv) {
  const out = { startDate: '7daysAgo', endDate: 'yesterday' };
  for (let i = 0; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--start') out.startDate = argv[++i];
    else if (a === '--end') out.endDate = argv[++i];
    else if (a === '--help' || a === '-h') {
      console.log('Uso: node ingest-ga4.js [--start <date>] [--end <date>]');
      process.exit(0);
    } else {
      console.error(`Argomento sconosciuto: ${a}`);
      process.exit(2);
    }
  }
  return out;
}

if (require.main === module) {
  run().catch((err) => {
    console.error('Ingestion GA4 fallita:', err);
    process.exit(1);
  });
}

module.exports = { loadArticlesWithSlug, ingestForArticle, parseArgs };
