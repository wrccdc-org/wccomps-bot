"""Authentik API manager for web application."""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class _AuthentikClient:
    """Simple HTTP client wrapper for Authentik API."""

    def __init__(self, api_url: str, headers: dict[str, str]) -> None:
        self.api_url = api_url
        self.headers = headers

    def get(self, path: str, params: dict[str, str] | None = None) -> dict[str, object]:
        url = f"{self.api_url}{path}"
        response = requests.get(url, headers=self.headers, params=params, timeout=30)
        response.raise_for_status()
        result: dict[str, object] = response.json()
        return result

    def patch(self, path: str, data: dict[str, object]) -> dict[str, object]:
        url = f"{self.api_url}{path}"
        response = requests.patch(url, headers=self.headers, json=data, timeout=30)
        response.raise_for_status()
        result: dict[str, object] = response.json()
        return result


class AuthentikUserLinker:
    """Manage Authentik API interactions."""

    def __init__(self) -> None:
        self.api_url = settings.AUTHENTIK_URL
        self.token = settings.AUTHENTIK_TOKEN
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    @property
    def client(self) -> _AuthentikClient:
        """Simple HTTP client wrapper."""
        return _AuthentikClient(self.api_url, self.headers)

    def update_user_discord_id(self, authentik_user_id: str, discord_id: int) -> None:
        """
        Store Discord ID in Authentik user attributes.

        Args:
            authentik_user_id: Authentik user UUID (pk)
            discord_id: Discord user ID (snowflake)
        """
        try:
            # First, get the current user to preserve existing attributes
            user = self.client.get(f"/api/v3/core/users/{authentik_user_id}/")

            # Update attributes (preserve existing, add discord_id)
            existing_attrs = user.get("attributes", {})
            attributes: dict[str, object] = dict(existing_attrs) if isinstance(existing_attrs, dict) else {}
            attributes["discord_id"] = str(discord_id)

            # Update user with merged attributes
            self.client.patch(
                f"/api/v3/core/users/{authentik_user_id}/",
                {"attributes": attributes},
            )
            logger.info(f"Updated Authentik user {authentik_user_id} with discord_id {discord_id}")
        except requests.HTTPError as e:
            if e.response.status_code == 403:
                logger.exception(
                    f"Authentik API token lacks permission to update user {authentik_user_id}. Error: {e.response.text}"
                )
            else:
                logger.exception(f"Failed to update Authentik user discord_id: {e}")
            raise
