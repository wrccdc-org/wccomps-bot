"""Authentik API manager for application control."""

import logging
from typing import TypedDict

import requests
from django.conf import settings


class AuthentikApplication(TypedDict):
    pk: str
    slug: str


class AuthentikBinding(TypedDict):
    pk: str
    enabled: bool


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
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _log_request(self, method: str, url: str, **kwargs: object) -> None:
        """Log HTTP request details (without sensitive headers)."""
        headers = kwargs.get("headers")
        safe_headers = {k: v for k, v in headers.items() if k != "Authorization"} if isinstance(headers, dict) else {}
        logger.debug(
            f"Authentik API Request: {method} {url} | Headers: {safe_headers} | "
            f"Params: {kwargs.get('params')} | Data: {kwargs.get('json')}"
        )

    def _handle_response_error(self, response: requests.Response, context: str) -> AuthentikAPIError:
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
            url=response.url,
        )

    def get_application_by_slug(self, slug: str) -> AuthentikApplication | None:
        """Get application details by slug."""
        url = f"{self.base_url}/api/v3/core/applications/"
        try:
            self._log_request("GET", url, params={"slug": slug})
            response = requests.get(
                url,
                headers=self.headers,
                params={"slug": slug},
                timeout=10,
            )
            response.raise_for_status()
            results: list[AuthentikApplication] = response.json().get("results", [])

            if not results:
                return None

            app: AuthentikApplication = results[0]
            logger.info(f"Found application '{slug}' with pk={app.get('pk')}")
            return app
        except requests.exceptions.HTTPError as e:
            error = self._handle_response_error(e.response, f"Get application '{slug}'")
            logger.exception(str(error))
            return None
        except requests.exceptions.RequestException as e:
            logger.exception(f"Network error getting application '{slug}': {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error getting application '{slug}': {e}", exc_info=True)
            return None

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

            response = requests.get(
                url,
                headers=self.headers,
                params={"target": app_pk},
                timeout=10,
            )
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

        except requests.exceptions.HTTPError as e:
            error = self._handle_response_error(e.response, f"Query bindings for app {app_pk}")
            logger.exception(f"Failed to query bindings: {error}")
            return None, str(error)
        except requests.exceptions.RequestException as e:
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

            response = requests.put(
                f"{self.base_url}/api/v3/policies/bindings/{binding_pk}/",
                headers=self.headers,
                json=binding,
                timeout=10,
            )
            response.raise_for_status()
            state = "enabled" if enabled else "disabled"
            logger.info(f"Set binding {binding_pk} to {state}")
            return True
        except Exception as e:
            logger.exception(f"Failed to update binding {binding.get('pk')}: {e}")
            return False

    def enable_application(self, app_slug: str) -> tuple[bool, str | None]:
        """Enable application for blue teams by disabling the BlueTeam group binding.

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

            # Disable the binding to allow blue team access
            success = self.update_binding_enabled(binding, enabled=False)

            if success:
                logger.info(f"✓ Application '{app_slug}' enabled for blue teams")
                return True, None
            error_msg = f"Failed to disable binding for application '{app_slug}'"
            logger.error(error_msg)
            return False, error_msg

        except Exception as e:
            error_msg = f"Unexpected error enabling application '{app_slug}': {e!s}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg

    def disable_application(self, app_slug: str) -> tuple[bool, str | None]:
        """Disable application for blue teams by enabling the BlueTeam group binding.

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

            # Enable the binding to block blue team access
            success = self.update_binding_enabled(binding, enabled=True)

            if success:
                logger.info(f"✓ Application '{app_slug}' disabled for blue teams")
                return True, None
            error_msg = f"Failed to enable binding for application '{app_slug}'"
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
        """Store Discord ID in Authentik user's custom attributes."""
        try:
            response = requests.patch(
                f"{self.base_url}/api/v3/core/users/{authentik_user_id}/",
                headers=self.headers,
                json={"attributes": {"discord_id": str(discord_id)}},
                timeout=10,
            )
            response.raise_for_status()
            logger.info(f"Updated discord_id for Authentik user {authentik_user_id}")
            return True
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
            response = requests.get(
                f"{self.base_url}/api/v3/core/users/",
                headers=self.headers,
                params={"username": username},
                timeout=10,
            )
            response.raise_for_status()
            users = response.json().get("results", [])

            if not users:
                return False, f"User {username} not found", 0

            user_pk = users[0]["pk"]
            logger.info(f"Found user {username} with pk={user_pk}")

            # Get all sessions for this user
            response = requests.get(
                f"{self.base_url}/api/v3/core/authenticated_sessions/",
                headers=self.headers,
                params={"user": user_pk},
                timeout=10,
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
                    response = requests.delete(
                        f"{self.base_url}/api/v3/core/authenticated_sessions/{session_uuid}/",
                        headers=self.headers,
                        timeout=10,
                    )
                    response.raise_for_status()
                    revoked_count += 1
                    logger.info(f"Revoked session {session_uuid} for user {username}")
                except Exception as e:
                    logger.warning(f"Failed to revoke session {session_uuid}: {e}")

            return True, None, revoked_count

        except requests.exceptions.HTTPError as e:
            error = self._handle_response_error(e.response, f"Revoke sessions for user {username}")
            logger.exception(str(error))
            return False, str(error), 0
        except requests.exceptions.RequestException as e:
            error_msg = f"Network error revoking sessions: {e}"
            logger.exception(error_msg)
            return False, error_msg, 0
        except Exception as e:
            error_msg = f"Unexpected error revoking sessions: {e}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg, 0
