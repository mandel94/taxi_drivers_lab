'use strict';

const fs = require('fs');
const path = require('path');

const DEFAULT_TOKEN_PATH = path.join(__dirname, 'ga4_token.json');
const DEFAULT_SECRETS_PATH = path.join(__dirname, 'ga4_client_secrets.json');

/**
 * Client OAuth2.0 "installed app" per la GA4 Data API v1beta.
 *
 * Pattern analogo a wp-client.js: una sola istanza condivisa,
 * autenticazione gestita internamente, token persistito su disco e
 * riusato/rinnovato in automatico. Il resto della codebase non deve mai
 * importare direttamente `googleapis`: passa sempre da qui.
 *
 * La dipendenza da `googleapis` e' caricata lazy (require dentro al
 * metodo), cosi' i test che istanziano `GA4Client` con un `transport`
 * finto non pagano il costo del modulo e non devono installare il
 * pacchetto solo per fare gira il test runner.
 *
 * Per i test: passare `transport: mockTransport` al costruttore.
 * Il mockTransport riceve (path, body) e ritorna l'oggetto risposta
 * GA4 gia' normalizzato (vedi normalizeRunReportResponse in
 * ga4-service.js).
 */
class GA4Client {
  constructor({
    tokenPath = DEFAULT_TOKEN_PATH,
    secretsPath = DEFAULT_SECRETS_PATH,
    transport = null,
  } = {}) {
    this.tokenPath = tokenPath;
    this.secretsPath = secretsPath;
    this._transport = transport;
  }

  /**
   * Esegue `runReport` sulla GA4 Data API v1beta.
   *
   * Il service layer (ga4-service.js) costruisce il body della request
   * (dimensions, metrics, dateRanges) e lo passa qui. Questo metodo
   * aggiunge solo l'header Authorization e l'invio.
   *
   * Restituisce la risposta cosi' come arriva dall'API (forma GA4):
   *   { dimensionHeaders: [...], metricHeaders: [...], rows: [...] }
   *
   * Se al costruttore e' stato passato un `transport` finto, viene
   * usato quello al posto della chiamata HTTP reale.
   */
  async runReport(propertyId, requestBody) {
    if (!propertyId) {
      throw new Error('GA4Client.runReport: propertyId mancante.');
    }
    if (!requestBody || typeof requestBody !== 'object') {
      throw new Error('GA4Client.runReport: requestBody mancante o non valido.');
    }

    if (this._transport) {
      return this._transport(
        `properties/${propertyId}:runReport`,
        requestBody,
      );
    }

    const { google } = _loadGoogleApis();
    const auth = await this._getAuthClient(google);
    const analyticsData = google.analyticsdata('v1beta');

    return analyticsData.properties.runReport({
      property: `properties/${propertyId}`,
      requestBody,
      auth,
    });
  }

  async _getAuthClient(google) {
    const { OAuth2Client } = _loadGoogleAuthLibrary(google);

    let credentials = null;
    if (fs.existsSync(this.tokenPath)) {
      try {
        credentials = JSON.parse(fs.readFileSync(this.tokenPath, 'utf8'));
      } catch {
        credentials = null;
      }
    }

    const secrets = _loadClientSecrets(this.secretsPath);

    const oauth2 = new OAuth2Client(
      secrets.client_id,
      secrets.client_secret,
      secrets.redirect_uris && secrets.redirect_uris[0],
    );

    if (credentials) {
      oauth2.setCredentials(credentials);
      if (credentials.expiry_date && credentials.expiry_date <= Date.now()) {
        const { credentials: refreshed } = await oauth2.refreshAccessToken();
        oauth2.setCredentials(refreshed);
        fs.writeFileSync(this.tokenPath, JSON.stringify(refreshed, null, 2));
      }
      return oauth2;
    }

    throw new Error(
      `Token GA4 non trovato in ${this.tokenPath}. ` +
        'Eseguire il flusso OAuth installed-app la prima volta e salvare il token su disco ' +
        '(vedi README di wp_client per i passaggi su Google Cloud Console).',
    );
  }
}

function _loadGoogleApis() {
  // Lazy require: evita di tirare dentro googleapis quando si usano mock.
  try {
    return require('googleapis').google;
  } catch (err) {
    throw new Error(
      'Pacchetto `googleapis` non installato. Installare con `npm install googleapis` ' +
        'oppure passare un `transport` finto al costruttore di GA4Client (es. nei test).',
    );
  }
}

function _loadGoogleAuthLibrary(_google) {
  return _loadGoogleApis().auth;
}

function _loadClientSecrets(secretsPath) {
  if (!fs.existsSync(secretsPath)) {
    throw new Error(
      `Client secrets non trovato: ${secretsPath}. ` +
        'Scaricare da Google Cloud Console (Credenziali > ID client OAuth > App desktop).',
    );
  }
  return JSON.parse(fs.readFileSync(secretsPath, 'utf8')).installed ||
         JSON.parse(fs.readFileSync(secretsPath, 'utf8')).web;
}

module.exports = { GA4Client };
