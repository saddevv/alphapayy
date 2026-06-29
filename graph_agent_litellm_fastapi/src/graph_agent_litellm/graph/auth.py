import threading
import time

from msal import ConfidentialClientApplication

from graph_agent_litellm.core.config import Settings
from graph_agent_litellm.core.errors import AuthenticationError


class GraphTokenProvider:
    """Thread-safe client-credential token provider for Microsoft Graph."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._client: ConfidentialClientApplication | None = None
        self._access_token: str | None = None
        self._expires_at = 0.0

    def get_token(self) -> str:
        if self._access_token and self._expires_at > time.time():
            return self._access_token

        with self._lock:
            if self._access_token and self._expires_at > time.time():
                return self._access_token
            return self._refresh_token()

    def _refresh_token(self) -> str:
        if not all(
            [
                self._settings.graph_tenant_id,
                self._settings.graph_client_id,
                self._settings.graph_client_secret,
            ]
        ):
            raise AuthenticationError(
                "Missing Microsoft Graph credentials. Set GRAPH_TENANT_ID, "
                "GRAPH_CLIENT_ID, and GRAPH_CLIENT_SECRET."
            )

        if self._client is None:
            self._client = ConfidentialClientApplication(
                client_id=self._settings.graph_client_id,
                client_credential=self._settings.graph_client_secret,
                authority=f"https://login.microsoftonline.com/{self._settings.graph_tenant_id}",
            )

        result = self._client.acquire_token_for_client(scopes=self._settings.graph_scopes)
        token = result.get("access_token")
        if not token:
            raise AuthenticationError(
                "Failed to acquire Microsoft Graph access token.",
                details={"provider_error": result.get("error_description") or result.get("error")},
            )

        expires_in = int(result.get("expires_in", 3600))
        self._access_token = token
        self._expires_at = time.time() + expires_in - 60
        return token

