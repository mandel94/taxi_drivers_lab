'use strict';

const WPAPI = require('wpapi');

const SITE_URL = 'https://www.taxidrivers.it';
const API_ROOT = `${SITE_URL}/wp-json`;

/**
 * Istanza condivisa del client.
 *
 * NOTA SU AUTODISCOVERY: WPAPI.discover(SITE_URL) è il pattern preferito
 * in generale, perché legge l'header HTTP `Link: <...>; rel="https://api.w.org/"`
 * dalla risposta della root del sito per individuare l'endpoint dell'API.
 * Su taxidrivers.it quell'header specifico non viene esposto (verificato:
 * il body JSON di /wp-json/ è comunque valido e il namespace wp/v2 è
 * pienamente attivo, quindi non è un problema dell'API in sé, solo
 * dell'header usato per l'autodiscovery, probabilmente filtrato da uno
 * dei plugin di caching/sicurezza attivi sul sito).
 *
 * Per questo si usa WPAPI.site(API_ROOT), che costruisce il client
 * puntando direttamente all'endpoint noto invece di derivarlo dagli
 * header. È il fallback documentato e supportato nativamente dalla
 * libreria per questo scenario, non una soluzione improvvisata.
 *
 * Se in futuro il sito espone di nuovo l'header (es. dopo una modifica
 * a un plugin), si può tornare a WPAPI.discover(SITE_URL) senza altre
 * modifiche al resto del codice, dato che l'oggetto risultante espone
 * la stessa interfaccia.
 */
let siteInstance = null;

function getSite() {
  if (!siteInstance) {
    siteInstance = Promise.resolve(new WPAPI({ endpoint: API_ROOT }));
  }
  return siteInstance;
}

module.exports = { getSite, SITE_URL, API_ROOT };