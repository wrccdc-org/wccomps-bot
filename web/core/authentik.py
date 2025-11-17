"""Authentik API manager for web application."""

import logging
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


class AuthentikManager:
    """Manage Authentik API interactions."""

    def __init__(self) -> None:
        self.api_url = settings.AUTHENTIK_URL
        self.token = settings.AUTHENTIK_TOKEN
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    @property
    def client(self) -> Any:
        """Simple HTTP client wrapper."""

        class Client:
            def __init__(self, api_url: str, headers: dict[str, str]) -> None:
                self.api_url = api_url
                self.headers = headers

            def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
                url = f"{self.api_url}{path}"
                response = requests.get(url, headers=self.headers, params=params, timeout=30)
                response.raise_for_status()
                return response.json()

            def patch(self, path: str, data: dict[str, Any]) -> Any:
                url = f"{self.api_url}{path}"
                response = requests.patch(url, headers=self.headers, json=data, timeout=30)
                response.raise_for_status()
                return response.json()

        return Client(self.api_url, self.headers)

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
            attributes = user.get("attributes", {})
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

    def get_user_by_discord_id(self, discord_id: int) -> dict[str, Any] | None:
        """
        Find Authentik user by Discord ID.

        Args:
            discord_id: Discord user ID (snowflake)

        Returns:
            dict: User data or None if not found
        """
        try:
            # Search for user with discord_id attribute
            response = self.client.get(
                "/api/v3/core/users/",
                params={"attributes__discord_id": str(discord_id)},
            )
            results = response.get("results", [])
            return results[0] if results else None
        except Exception as e:
            logger.exception(f"Failed to search for user by discord_id: {e}")
            return None
