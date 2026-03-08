"""Authentik API manager for application control."""

import logging
from typing import TypedDict
from urllib.parse import quote

import httpx
from django.conf import settings


class AuthentikApplication(TypedDict):
    pk: str
    slug: str


class AuthentikBinding(TypedDict):
    pk: str
    enabled: bool


class AuthentikUser(TypedDict):
    pk: int
    username: str


logger = logging.getLogger(__name__)


class AuthentikAPIError(Exception):
    """Custom exception for Authentik API errors with detailed information."""

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response_text: str | None = None,
        url: str | None = None,
    ) -> None:
        self.message = message
        self.status_code = status_code
        self.response_text = response_text
        self.url = url
        super().__init__(self.formatted_message())

    def formatted_message(self) -> str:
        """Format error message with all details."""
        parts = [self.message]
        if self.status_code:
            parts.append(f"Status: {self.status_code}")
        if self.url:
            parts.append(f"URL: {self.url}")
        if self.response_text:
            parts.append(f"Response: {self.response_text[:500]}")
        return " | ".join(parts)


class AuthentikManager:
    """Manager for Authentik API operations."""

    def __init__(self) -> None:
        self.base_url = settings.AUTHENTIK_URL
        self.token = settings.AUTHENTIK_TOKEN
        self.client = httpx.Client(
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )

    def _log_request(self, method: str, url: str, **kwargs: object) -> None:
        """Log HTTP request details (without sensitive headers)."""
        headers = kwargs.get("headers")
        safe_headers = {k: v for k, v in headers.items() if k != "Authorization"} if isinstance(headers, dict) else {}
        logger.debug(
            f"Authentik API Request: {method} {url} | Headers: {safe_headers} | "
            f"Params: {kwargs.get('params')} | Data: {kwargs.get('json')}"
        )

    def _handle_response_error(self, response: httpx.Response, context: str) -> AuthentikAPIError:
        """Create detailed error from HTTP response."""
        try:
            error_data = response.json()
            error_detail = error_data.get("detail", str(error_data))
        except Exception:
            error_detail = response.text

        # Map common status codes to readable messages
        status_messages = {
            401: "Authentication failed - check AUTHENTIK_TOKEN",
            403: "Permission denied - token lacks required permissions",
            404: "Resource not found",
            429: "Rate limit exceeded",
            500: "Authentik server error",
            502: "Bad gateway - Authentik may be down",
            503: "Service unavailable - Authentik may be overloaded",
        }

        status_msg = status_messages.get(response.status_code, "HTTP error")
        message = f"{context}: {status_msg}"

        return AuthentikAPIError(
            message=message,
            status_code=response.status_code,
            response_text=error_detail,
            url=str(response.url),
        )

    def list_applications(self) -> list[str]:
        """List all application slugs from Authentik."""
        url = f"{self.base_url}/api/v3/core/applications/"
        slugs: list[str] = []
        try:
            self._log_request("GET", url)
            response = self.client.get(url, params={"page_size": 100})
            response.raise_for_status()
            results = response.json().get("results", [])
            slugs = sorted([app.get("slug", "") for app in results if app.get("slug")])
            logger.info(f"Found {len(slugs)} applications in Authentik")
            return slugs
        except Exception as e:
            logger.exception(f"Failed to list applications: {e}")
            return slugs

    def get_application_by_slug(self, slug: str) -> AuthentikApplication | None:
        """Get application details by exact slug match."""
        url = f"{self.base_url}/api/v3/core/applications/"
        try:
            self._log_request("GET", url, params={"slug": slug})
            response = self.client.get(url, params={"slug": slug})
            response.raise_for_status()
            results: list[AuthentikApplication] = response.json().get("results", [])

            # API does substring matching, so filter for exact slug
            for app in results:
                if app.get("slug") == slug:
                    logger.info(f"Found application '{slug}' with pk={app.get('pk')}")
                    return app

            logger.warning(f"No exact match for slug '{slug}' (got {len(results)} partial matches)")
            return None
        except httpx.HTTPStatusError as e:
            error = self._handle_response_error(e.response, f"Get application '{slug}'")
            logger.exception(str(error))
            return None
        except httpx.HTTPError as e:
            logger.exception(f"Network error getting application '{slug}': {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting application '{slug}': {e}", exc_info=True)
            return None

    def list_blueteam_applications(self) -> list[str]:
        """List only application slugs that have a BlueTeam group binding."""
        all_slugs = self.list_applications()
        bt_slugs: list[str] = []
        for slug in all_slugs:
            app = self.get_application_by_slug(slug)
            if not app:
                continue
            binding, _ = self.get_blueteam_binding(app["pk"])
            if binding:
                bt_slugs.append(slug)
                logger.info(f"App '{slug}' has BlueTeam binding")
            else:
                logger.debug(f"App '{slug}' has no BlueTeam binding, skipping")
        logger.info(f"Found {len(bt_slugs)} apps with BlueTeam bindings: {bt_slugs}")
        return bt_slugs

    def get_blueteam_binding(self, app_pk: str) -> tuple[AuthentikBinding | None, str | None]:
        """Get the BlueTeam group binding by querying application bindings.

        Args:
            app_pk: Application primary key to query bindings for

        Returns:
            tuple[Optional[dict], Optional[str]]: (binding_object, error_message)
        """
        url = f"{self.base_url}/api/v3/policies/bindings/"
        try:
            logger.debug(f"Querying bindings for application {app_pk}")
            self._log_request("GET", url, params={"target": app_pk})

            response = self.client.get(url, params={"target": app_pk})
            response.raise_for_status()
            bindings = response.json().get("results", [])

            logger.debug(f"Found {len(bindings)} binding(s) for application {app_pk}")

            # Find the BlueTeam group binding
            for binding in bindings:
                group_obj = binding.get("group_obj", {})
                binding_pk = binding.get("pk")

                # Check if this is a BlueTeam group binding
                if group_obj:
                    group_name = group_obj.get("name", "")
                    logger.debug(f"Found group binding: {group_name} (pk={binding_pk})")

                    if "blueteam" in group_name.lower():
                        logger.info(f"Found blueteam group binding: {binding_pk} (group={group_name})")
                        return binding, None

            error_msg = (
                f"No BlueTeam group binding found for application {app_pk}. "
                f"Found {len(bindings)} binding(s) but none matched."
            )
            logger.error(error_msg)
            return None, error_msg

        except httpx.HTTPStatusError as e:
            error = self._handle_response_error(e.response, f"Query bindings for app {app_pk}")
            logger.exception(f"Failed to query bindings: {error}")
            return None, str(error)
        except httpx.HTTPError as e:
            error_msg = f"Network error querying bindings: {e}"
            logger.exception(error_msg)
            return None, error_msg
        except Exception as e:
            error_msg = f"Unexpected error querying bindings: {e}"
            logger.error(error_msg, exc_info=True)
            return None, error_msg

    def update_binding_enabled(self, binding: AuthentikBinding, enabled: bool) -> bool:
        """Update the enabled state of a binding.

        Args:
            binding: The binding object to update
            enabled: True to enable the binding (block access), False to disable (allow access)
        """
        try:
            binding_pk = binding["pk"]

            # Modify the enabled field and PUT the entire object back
            binding["enabled"] = enabled

            response = self.client.put(
                f"{self.base_url}/api/v3/policies/bindings/{binding_pk}/",
                json=binding,
            )
            response.raise_for_status()
            state = "enabled" if enabled else "disabled"
            logger.info(f"Set binding {binding_pk} to {state}")
            return True
        except Exception as e:
            logger.exception(f"Failed to update binding {binding.get('pk')}: {e}")
            return False

    def enable_application(self, app_slug: str) -> tuple[bool, str | None]:
        """Enable application for blue teams by enabling the BlueTeam group binding.

        Returns:
            tuple[bool, Optional[str]]: (success, error_message)
        """
        try:
            logger.info(f"Attempting to enable application '{app_slug}'")

            app = self.get_application_by_slug(app_slug)
            if not app:
                error_msg = f"Application '{app_slug}' not found in Authentik"
                logger.error(error_msg)
                return False, error_msg

            app_pk = app["pk"]
            logger.debug(f"Application '{app_slug}' has pk={app_pk}")

            # Find the BlueTeam group binding
            binding, binding_error = self.get_blueteam_binding(app_pk)
            if not binding:
                error_msg = f"Could not find BlueTeam group binding: {binding_error}"
                logger.error(error_msg)
                return False, error_msg

            logger.debug(f"Using binding pk={binding['pk']}")

            # Enable the binding to allow blue team access
            success = self.update_binding_enabled(binding, enabled=True)

            if success:
                logger.info(f"✓ Application '{app_slug}' enabled for blue teams")
                return True, None
            error_msg = f"Failed to enable binding for application '{app_slug}'"
            logger.error(error_msg)
            return False, error_msg

        except Exception as e:
            error_msg = f"Unexpected error enabling application '{app_slug}': {e!s}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    def disable_application(self, app_slug: str) -> tuple[bool, str | None]:
        """Disable application for blue teams by disabling the BlueTeam group binding.

        Returns:
            tuple[bool, Optional[str]]: (success, error_message)
        """
        try:
            logger.info(f"Attempting to disable application '{app_slug}'")

            app = self.get_application_by_slug(app_slug)
            if not app:
                error_msg = f"Application '{app_slug}' not found in Authentik"
                logger.error(error_msg)
                return False, error_msg

            app_pk = app["pk"]
            logger.debug(f"Application '{app_slug}' has pk={app_pk}")

            # Find the BlueTeam group binding
            binding, binding_error = self.get_blueteam_binding(app_pk)
            if not binding:
                error_msg = f"Could not find BlueTeam group binding: {binding_error}"
                logger.error(error_msg)
                return False, error_msg

            logger.debug(f"Using binding pk={binding['pk']}")

            # Disable the binding to block blue team access
            success = self.update_binding_enabled(binding, enabled=False)

            if success:
                logger.info(f"✓ Application '{app_slug}' disabled for blue teams")
                return True, None
            error_msg = f"Failed to disable binding for application '{app_slug}'"
            logger.error(error_msg)
            return False, error_msg

        except Exception as e:
            error_msg = f"Unexpected error disabling application '{app_slug}': {e!s}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    def enable_applications(self, app_slugs: list[str]) -> dict[str, tuple[bool, str | None]]:
        """Enable multiple applications for blue teams.

        Returns:
            dict mapping app_slug to (success, error_message)
        """
        logger.info(f"Enabling {len(app_slugs)} applications: {app_slugs}")
        results: dict[str, tuple[bool, str | None]] = {}
        for slug in app_slugs:
            results[slug] = self.enable_application(slug)

        success_count = sum(1 for success, _ in results.values() if success)
        logger.info(f"Enable applications complete: {success_count}/{len(app_slugs)} succeeded")
        return results

    def disable_applications(self, app_slugs: list[str]) -> dict[str, tuple[bool, str | None]]:
        """Disable multiple applications for blue teams.

        Returns:
            dict mapping app_slug to (success, error_message)
        """
        logger.info(f"Disabling {len(app_slugs)} applications: {app_slugs}")
        results: dict[str, tuple[bool, str | None]] = {}

        # Disable each application
        for slug in app_slugs:
            results[slug] = self.disable_application(slug)

        success_count = sum(1 for success, _ in results.values() if success)
        logger.info(f"Disable applications complete: {success_count}/{len(app_slugs)} succeeded")
        return results

    def update_user_discord_id(self, authentik_user_id: str, discord_id: int) -> bool:
        """Store Discord ID in Authentik user attributes, preserving existing attributes.

        Args:
            authentik_user_id: Authentik user UUID (pk)
            discord_id: Discord user ID (snowflake)
        """
        try:
            # First, get the current user to preserve existing attributes
            response = self.client.get(
                f"{self.base_url}/api/v3/core/users/{authentik_user_id}/",
            )
            response.raise_for_status()
            user = response.json()

            # Update attributes (preserve existing, add discord_id)
            existing_attrs = user.get("attributes", {})
            attributes: dict[str, object] = dict(existing_attrs) if isinstance(existing_attrs, dict) else {}
            attributes["discord_id"] = str(discord_id)

            # Update user with merged attributes
            response = self.client.patch(
                f"{self.base_url}/api/v3/core/users/{authentik_user_id}/",
                json={"attributes": attributes},
            )
            response.raise_for_status()
            logger.info(f"Updated discord_id for Authentik user {authentik_user_id}")
            return True
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                logger.exception(
                    f"Authentik API token lacks permission to update user {authentik_user_id}. Error: {e.response.text}"
                )
            else:
                logger.exception(f"Failed to update Authentik user discord_id: {e}")
            raise
        except Exception as e:
            logger.exception(f"Failed to update discord_id for user {authentik_user_id}: {e}")
            return False

    def revoke_user_sessions(self, username: str) -> tuple[bool, str | None, int]:
        """Revoke all active sessions for a user by username.

        Args:
            username: Authentik username (e.g., "team01")

        Returns:
            tuple[bool, Optional[str], int]: (success, error_message, sessions_revoked)
        """
        try:
            # First, get the user
            response = self.client.get(
                f"{self.base_url}/api/v3/core/users/",
                params={"username": username},
            )
            response.raise_for_status()
            users = response.json().get("results", [])

            if not users:
                return False, f"User {username} not found", 0

            user_pk = users[0]["pk"]
            logger.info(f"Found user {username} with pk={user_pk}")

            # Get all sessions for this user
            response = self.client.get(
                f"{self.base_url}/api/v3/core/authenticated_sessions/",
                params={"user": user_pk},
            )
            response.raise_for_status()
            sessions = response.json().get("results", [])

            logger.info(f"Found {len(sessions)} session(s) for user {username}")

            # Revoke each session
            revoked_count = 0
            for session in sessions:
                session_uuid = session.get("uuid")
                if not session_uuid:
                    continue

                try:
                    response = self.client.delete(
                        f"{self.base_url}/api/v3/core/authenticated_sessions/{session_uuid}/",
                    )
                    response.raise_for_status()
                    revoked_count += 1
                    logger.info(f"Revoked session {session_uuid} for user {username}")
                except Exception as e:
                    logger.warning(f"Failed to revoke session {session_uuid}: {e}")

            return True, None, revoked_count

        except httpx.HTTPStatusError as e:
            error = self._handle_response_error(e.response, f"Revoke sessions for user {username}")
            logger.exception(str(error))
            return False, str(error), 0
        except httpx.HTTPError as e:
            error_msg = f"Network error revoking sessions: {e}"
            logger.exception(error_msg)
            return False, error_msg, 0
        except Exception as e:
            error_msg = f"Unexpected error revoking sessions: {e}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg, 0

    def toggle_user(self, username: str, is_active: bool) -> tuple[bool, str]:
        """Enable or disable a team account in Authentik with safety checks.

        Args:
            username: Authentik username (e.g., "team01")
            is_active: True to enable, False to disable

        Returns:
            (success: bool, error_message: str)
        """
        from core.authentik_utils import validate_team_account

        try:
            response = self.client.get(
                f"{self.base_url}/api/v3/core/users/?username={quote(username, safe='')}",
            )
            response.raise_for_status()
            users: list[AuthentikUser] = response.json().get("results", [])

            if not users:
                return (False, "User not found")

            user: AuthentikUser = users[0]

            # Safety check: Verify this is actually a team account
            is_valid, error = validate_team_account(user, username)
            if not is_valid:
                return (False, error)

            response = self.client.patch(
                f"{self.base_url}/api/v3/core/users/{user['pk']}/",
                json={"is_active": is_active},
            )
            response.raise_for_status()
            return (True, "")
        except Exception as e:
            logger.exception(f"Failed to toggle {username}: {e}")
            return (False, "Account toggle failed - check server logs")

    def reset_blueteam_password(self, team_number: int, password: str) -> tuple[bool, str]:
        """Reset a blue team account's password in Authentik and enable the account.

        Args:
            team_number: Team number (1-50)
            password: New password to set

        Returns:
            Tuple of (success: bool, error_message: str)
        """
        from core.authentik_utils import validate_team_account
        from team.models import MAX_TEAMS

        if team_number < 1 or team_number > MAX_TEAMS:
            return (False, f"Team number must be between 1 and {MAX_TEAMS}")

        username = f"team{team_number:02d}"

        try:
            # Get user by username
            response = self.client.get(
                f"{self.base_url}/api/v3/core/users/?username={quote(username, safe='')}",
            )
            response.raise_for_status()
            users: list[AuthentikUser] = response.json().get("results", [])

            if not users:
                return (False, f"User {username} not found")

            user: AuthentikUser = users[0]
            user_pk: int = user["pk"]

            # Safety check: Verify this is actually a team account
            is_valid, error = validate_team_account(user, username)
            if not is_valid:
                return (False, error)

            # Set password
            response = self.client.post(
                f"{self.base_url}/api/v3/core/users/{user_pk}/set_password/",
                json={"password": password},
            )
            response.raise_for_status()

            # Enable user account (set is_active=True)
            response = self.client.patch(
                f"{self.base_url}/api/v3/core/users/{user_pk}/",
                json={"is_active": True},
            )
            response.raise_for_status()

            return (True, "")

        except Exception as e:
            logger.exception(f"Failed to reset password for {username}: {e}")
            return (False, "Password reset failed - check server logs")
