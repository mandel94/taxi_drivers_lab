"""
ga4_client.py

Modulo di connessione alla GA4 Data API (v1beta) via OAuth2.0, per la
pipeline taxidrivers.it. Espone GA4Client, che isola il resto della
codebase Python dalla libreria google-analytics-data — stesso
principio di service layer isolation gia' adottato in wp_client per
Node (posts-service.js non chiama mai wpapi direttamente).

Autenticazione: OAuth2.0 "installed app" con client_secrets.json
scaricato da Google Cloud Console (vedi PROMPT_ga4client.md per i
passaggi). Il token risultante (incluso refresh token) viene salvato
in locale al primo consenso e riusato/rinnovato in automatico alle
esecuzioni successive, senza intervento manuale.

property_id non e' legato all'istanza ma passato a run_query/
run_report: lo stesso client puo' cosi' interrogare piu' proprieta'
GA4 nella stessa sessione, utile se in futuro si aggiungono altri
siti oltre a taxidrivers.it.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)
from google.api_core.exceptions import DeadlineExceeded, ServiceUnavailable
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]

# Le stesse 8 metriche definite in fact_ga4_daily (migrazione 0002).
# ATTENZIONE (vedi commento SQL sulla colonna sessions): active_users,
# sessions, engaged_sessions, engagement_rate, bounce_rate e
# average_session_duration sono metriche di sessione/utente ad
# attribuzione "a tocco" per pagina — non sommano al totale sito.
# screen_page_views e user_engagement_duration sono genuinamente
# per-pagina e sommano correttamente.
GA4_METRICS = [
    "activeUsers",
    "screenPageViews",
    "sessions",
    "engagedSessions",
    "engagementRate",
    "bounceRate",
    "averageSessionDuration",
    "userEngagementDuration",
]

# Mappa nome GA4 (camelCase) -> nome colonna fact_ga4_daily (snake_case)
GA4_TO_COLUMN = {
    "activeUsers": "active_users",
    "screenPageViews": "screen_page_views",
    "sessions": "sessions",
    "engagedSessions": "engaged_sessions",
    "engagementRate": "engagement_rate",
    "bounceRate": "bounce_rate",
    "averageSessionDuration": "average_session_duration",
    "userEngagementDuration": "user_engagement_duration",
}

GA4_DIMENSIONS = ["pagePath", "date"]

_INT_COLUMNS = ["active_users", "screen_page_views", "sessions", "engaged_sessions"]
_FLOAT_COLUMNS = [
    "engagement_rate",
    "bounce_rate",
    "average_session_duration",
    "user_engagement_duration",
]

# Solo errori transitori vengono ritentati. Un property_id invalido,
# credenziali scadute o permessi mancanti non sono transitori: si
# propagano subito, non vengono silenziati dietro un retry.
_RETRYABLE_EXCEPTIONS = (DeadlineExceeded, ServiceUnavailable)


class GA4Client:
    """
    Client OAuth2.0 "installed app" per la GA4 Data API, scope readonly.

    Non chiamare mai BetaAnalyticsDataClient direttamente altrove nel
    codice: passare sempre da qui.
    """

    def __init__(
        self,
        client_secrets_path: str | Path = "client_secrets.json",
        token_path: str | Path = "token.json",
        scopes: list[str] | None = None,
    ) -> None:
        base_dir = Path(__file__).resolve().parent
        self.client_secrets_path = Path(client_secrets_path)
        self.token_path = Path(token_path)
        if not self.client_secrets_path.is_absolute():
            self.client_secrets_path = base_dir / self.client_secrets_path
        if not self.token_path.is_absolute():
            self.token_path = base_dir / self.token_path
        self.scopes = scopes or SCOPES
        self._client = BetaAnalyticsDataClient(credentials=self._get_credentials())

    def _get_credentials(self) -> Credentials:
        creds: Credentials | None = None

        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), self.scopes)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.client_secrets_path.exists():
                    raise FileNotFoundError(
                        f"Client secrets non trovato: {self.client_secrets_path}. "
                        "Vedi PROMPT_ga4client.md per come scaricarlo da Google "
                        "Cloud Console (Credenziali > Crea credenziali > ID "
                        "client OAuth > tipo 'App desktop')."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.client_secrets_path), self.scopes
                )
                creds = flow.run_local_server(port=0)

            self.token_path.write_text(creds.to_json())

        return creds

    def _run_with_retry(self, request: RunReportRequest, max_retries: int):
        for attempt in range(max_retries):
            try:
                return self._client.run_report(request)
            except _RETRYABLE_EXCEPTIONS:
                if attempt == max_retries - 1:
                    raise
                time.sleep(2**attempt)

    def run_query(
        self,
        property_id: str,
        metrics: list[str],
        dimensions: list[str] | None = None,
        start_date: str = "7daysAgo",
        end_date: str = "yesterday",
        row_limit: int = 100_000,
        max_retries: int = 3,
    ) -> pd.DataFrame:
        """
        Query GA4 generica: nomi di dimensioni/metriche grezzi
        (camelCase, come li chiama la Data API), nessuna conversione
        di tipo o rinomina colonne. Utile per esplorazioni ad-hoc; per
        il caso d'uso fact_ga4_daily usare run_report.

        Gestisce la paginazione se le righe superano row_limit per
        singola richiesta. Riprova solo su errori transitori (timeout,
        servizio non disponibile), fino a max_retries tentativi con
        backoff esponenziale.
        """
        dimension_names = dimensions or []
        rows: list[dict] = []
        offset = 0

        while True:
            request = RunReportRequest(
                property=f"properties/{property_id}",
                dimensions=[Dimension(name=d) for d in dimension_names],
                metrics=[Metric(name=m) for m in metrics],
                date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
                limit=row_limit,
                offset=offset,
            )
            response = self._run_with_retry(request, max_retries)

            for row in response.rows:
                record = {}
                for header, value in zip(response.dimension_headers, row.dimension_values):
                    record[header.name] = value.value
                for header, value in zip(response.metric_headers, row.metric_values):
                    record[header.name] = value.value
                rows.append(record)

            offset += row_limit
            if offset >= response.row_count:
                break

        if not rows:
            return pd.DataFrame(columns=[*dimension_names, *metrics])
        return pd.DataFrame(rows)

    def run_report(
        self,
        property_id: str,
        start_date: str,
        end_date: str,
        max_retries: int = 3,
    ) -> pd.DataFrame:
        """
        Wrapper su run_query con dimensioni e metriche fissate per
        fact_ga4_daily. Ritorna un DataFrame con colonne snake_case e
        tipi gia' pronti per l'insert:
        page_path, event_date, active_users, screen_page_views,
        sessions, engaged_sessions, engagement_rate, bounce_rate,
        average_session_duration, user_engagement_duration
        (manca solo loaded_at, che ha default lato DB).
        """
        all_columns = ["page_path", "event_date", *_INT_COLUMNS, *_FLOAT_COLUMNS]

        df = self.run_query(
            property_id=property_id,
            dimensions=GA4_DIMENSIONS,
            metrics=GA4_METRICS,
            start_date=start_date,
            end_date=end_date,
            max_retries=max_retries,
        )

        if df.empty:
            return pd.DataFrame(columns=all_columns)

        df = df.rename(columns={"pagePath": "page_path", **GA4_TO_COLUMN})
        df["event_date"] = pd.to_datetime(df["date"], format="%Y%m%d").dt.date
        df = df.drop(columns=["date"])

        df[_INT_COLUMNS] = df[_INT_COLUMNS].astype(int)
        df[_FLOAT_COLUMNS] = df[_FLOAT_COLUMNS].astype(float)

        return df[all_columns]