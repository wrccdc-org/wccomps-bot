"""Utility for obtaining OIDC tokens from Authentik for service accounts."""

import logging
import time
from typing import Optional
import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class AuthentikTokenManager:
    """Manages OIDC token retrieval from Authentik for service accounts."""

    def __init__(
        self,
        authentik_url: str = "https://auth.wccomps.org",
        oauth_client_id: Optional[str] = None,
        oauth_client_secret: Optional[str] = None,
    ):
        """
        Initialize Authentik token manager.

        Args:
            authentik_url: Base URL for Authentik
            oauth_client_id: OAuth client ID for client credentials flow
            oauth_client_secret: OAuth client secret for client credentials flow
        """
        self.authentik_url = authentik_url.rstrip("/")
        self.oauth_client_id = oauth_client_id or getattr(
            settings, "QUOTIENT_OAUTH_CLIENT_ID", ""
        )
        self.oauth_client_secret = oauth_client_secret or getattr(
            settings, "QUOTIENT_OAUTH_CLIENT_SECRET", ""
        )

    def get_service_account_id_token(self) -> Optional[str]:
        """
        Get an access token for machine-to-machine authentication.

        This uses OAuth2 client credentials flow, which is designed for
        server-to-server authentication without requiring user credentials.

        Returns:
            Access token string or None if generation fails
        """
        cache_key = "quotient_m2m_token"

        # Check cache first
        cached = cache.get(cache_key)
        if cached:
            token, expiry = cached
            # Return cached token if it has more than 5 minutes left
            if time.time() < expiry - 300:
                logger.debug("Using cached M2M token")
                return str(token)

        # Validate configuration
        if not all([self.oauth_client_id, self.oauth_client_secret]):
            logger.error(
                "Missing required configuration for token generation. "
                "Need: oauth_client_id, oauth_client_secret"
            )
            return None

        # Get access token via OAuth client credentials flow
        try:
            token, expires_in = self._get_id_token_via_client_credentials()
            if token:
                # Cache for the token's lifetime minus 5 minute buffer
                cache_duration = max(expires_in - 300, 60)
                cache.set(cache_key, (token, time.time() + expires_in), cache_duration)
                logger.info(f"Obtained M2M token (expires in {expires_in}s)")
                return token
        except Exception as e:
            logger.error(f"Failed to get ID token: {e}")

        return None

    def _get_id_token_via_client_credentials(self) -> tuple[Optional[str], int]:
        """
        Get access token using OAuth2 Client Credentials flow.

        This is for machine-to-machine authentication and uses only the
        client ID and secret (no username/password needed).

        Returns:
            Tuple of (access_token, expires_in_seconds) or (None, 0) if failed
        """
        try:
            logger.debug("Requesting token via client credentials flow")

            response = requests.post(
                f"{self.authentik_url}/application/o/token/",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.oauth_client_id,
                    "client_secret": self.oauth_client_secret,
                    "scope": "openid profile groups email",
                },
                timeout=10,
            )
            response.raise_for_status()

            token_data = response.json()
            access_token = token_data.get("access_token")
            expires_in = token_data.get("expires_in", 3600)

            if not access_token:
                logger.error("OAuth response did not include access_token")
                return None, 0

            logger.debug(f"Received access token (expires in {expires_in}s)")
            return access_token, expires_in

        except requests.RequestException as e:
            logger.error(f"Client credentials request failed: {e}")
            if hasattr(e, "response") and e.response is not None:
                logger.error(f"Response body: {e.response.text[:200]}")
            return None, 0


# Global instance
_token_manager: Optional[AuthentikTokenManager] = None


def get_token_manager() -> AuthentikTokenManager:
    """Get or create global token manager instance."""
    global _token_manager
    if _token_manager is None:
        _token_manager = AuthentikTokenManager()
    return _token_manager
