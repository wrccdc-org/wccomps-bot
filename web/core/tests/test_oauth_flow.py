"""
Tests for OAuth flow with mocked Authentik responses.

These tests verify the full OAuth callback logic without requiring
a real Authentik server.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.test import Client

from core.models import UserGroups


@pytest.fixture
def oauth_state_session(client: Client) -> tuple[Client, str]:
    """Set up a client with valid OAuth state in session."""
    # Visit login to set up state
    with patch("core.oauth._get_oauth_config") as mock_config:
        mock_config.return_value = {
            "client_id": "test-client-id",
            "client_secret": "test-secret",
            "authorization_endpoint": "https://auth.example.com/authorize/",
            "token_endpoint": "https://auth.example.com/token/",
            "userinfo_endpoint": "https://auth.example.com/userinfo/",
            "end_session_endpoint": "https://auth.example.com/end-session/",
        }
        response = client.get("/auth/login/")
        assert response.status_code == 302

    pending = client.session.get("oauth_pending_states", [])
    assert len(pending) == 1
    state = pending[0]["state"]
    return client, state


@pytest.mark.django_db
class TestOAuthLogin:
    """Test OAuth login initiation."""

    def test_login_redirects_to_authentik(self):
        """Login should redirect to Authentik authorization endpoint."""
        client = Client()
        with patch("core.oauth._get_oauth_config") as mock_config:
            mock_config.return_value = {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "authorization_endpoint": "https://auth.example.com/authorize/",
                "token_endpoint": "https://auth.example.com/token/",
                "userinfo_endpoint": "https://auth.example.com/userinfo/",
                "end_session_endpoint": "https://auth.example.com/end-session/",
            }
            response = client.get("/auth/login/")

        assert response.status_code == 302
        assert "auth.example.com/authorize" in response.url
        assert "client_id=test-client-id" in response.url
        assert "scope=openid" in response.url

    def test_login_stores_state_in_session(self):
        """Login should store state in session for CSRF protection."""
        client = Client()
        with patch("core.oauth._get_oauth_config") as mock_config:
            mock_config.return_value = {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "authorization_endpoint": "https://auth.example.com/authorize/",
                "token_endpoint": "https://auth.example.com/token/",
                "userinfo_endpoint": "https://auth.example.com/userinfo/",
                "end_session_endpoint": "https://auth.example.com/end-session/",
            }
            client.get("/auth/login/")

        pending = client.session.get("oauth_pending_states", [])
        assert len(pending) == 1
        assert len(pending[0]["state"]) > 20  # Secure random

    def test_login_stores_next_url(self):
        """Login should store next URL for post-login redirect."""
        client = Client()
        with patch("core.oauth._get_oauth_config") as mock_config:
            mock_config.return_value = {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "authorization_endpoint": "https://auth.example.com/authorize/",
                "token_endpoint": "https://auth.example.com/token/",
                "userinfo_endpoint": "https://auth.example.com/userinfo/",
                "end_session_endpoint": "https://auth.example.com/end-session/",
            }
            client.get("/auth/login/?next=/dashboard/")

        pending = client.session.get("oauth_pending_states", [])
        assert len(pending) == 1
        assert pending[0]["next"] == "/dashboard/"

    def test_login_without_client_id_shows_error(self):
        """Login without client ID configured should show error."""
        client = Client()
        with patch("core.oauth._get_oauth_config") as mock_config:
            mock_config.return_value = {
                "client_id": "",
                "client_secret": "",
                "authorization_endpoint": "https://auth.example.com/authorize/",
                "token_endpoint": "https://auth.example.com/token/",
                "userinfo_endpoint": "https://auth.example.com/userinfo/",
                "end_session_endpoint": "https://auth.example.com/end-session/",
            }
            response = client.get("/auth/login/")

        assert response.status_code == 500
        assert b"Configuration Error" in response.content


@pytest.mark.django_db
class TestOAuthCallback:
    """Test OAuth callback handling."""

    def test_callback_creates_new_user(self, oauth_state_session):
        """Callback should create new user if not exists."""
        client, state = oauth_state_session

        mock_token_response = MagicMock()
        mock_token_response.json.return_value = {"access_token": "test-token"}
        mock_token_response.raise_for_status = MagicMock()

        mock_userinfo_response = MagicMock()
        mock_userinfo_response.json.return_value = {
            "sub": "unique-authentik-id-12345",
            "preferred_username": "newuser",
            "email": "newuser@example.com",
            "groups": ["WCComps_BlueTeam01", "BlueTeam"],
        }
        mock_userinfo_response.raise_for_status = MagicMock()

        with (
            patch("core.oauth._get_oauth_config") as mock_config,
            patch("core.oauth.httpx.Client") as mock_httpx,
        ):
            mock_config.return_value = {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "authorization_endpoint": "https://auth.example.com/authorize/",
                "token_endpoint": "https://auth.example.com/token/",
                "userinfo_endpoint": "https://auth.example.com/userinfo/",
                "end_session_endpoint": "https://auth.example.com/end-session/",
            }
            mock_client = MagicMock()
            mock_client.post.return_value = mock_token_response
            mock_client.get.return_value = mock_userinfo_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_httpx.return_value = mock_client

            response = client.get(f"/auth/callback/?code=test-code&state={state}")

        assert response.status_code == 302  # Redirect after success

        # Verify user created
        user = User.objects.get(username="newuser")
        assert user.email == "newuser@example.com"

        # Verify UserGroups created with correct groups
        user_groups = UserGroups.objects.get(user=user)
        assert user_groups.authentik_id == "unique-authentik-id-12345"
        assert "WCComps_BlueTeam01" in user_groups.groups
        assert "BlueTeam" in user_groups.groups

    def test_callback_updates_existing_user_groups(self, oauth_state_session):
        """Callback should update groups for existing user."""
        client, state = oauth_state_session

        # Create existing user with old groups
        user = User.objects.create_user(username="existinguser", email="existing@example.com")
        UserGroups.objects.create(
            user=user,
            authentik_id="existing-authentik-id",
            groups=["OldGroup"],
        )

        mock_token_response = MagicMock()
        mock_token_response.json.return_value = {"access_token": "test-token"}
        mock_token_response.raise_for_status = MagicMock()

        mock_userinfo_response = MagicMock()
        mock_userinfo_response.json.return_value = {
            "sub": "existing-authentik-id",
            "preferred_username": "existinguser",
            "email": "existing@example.com",
            "groups": ["WCComps_GoldTeam", "NewGroup"],
        }
        mock_userinfo_response.raise_for_status = MagicMock()

        with (
            patch("core.oauth._get_oauth_config") as mock_config,
            patch("core.oauth.httpx.Client") as mock_httpx,
        ):
            mock_config.return_value = {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "authorization_endpoint": "https://auth.example.com/authorize/",
                "token_endpoint": "https://auth.example.com/token/",
                "userinfo_endpoint": "https://auth.example.com/userinfo/",
                "end_session_endpoint": "https://auth.example.com/end-session/",
            }
            mock_client = MagicMock()
            mock_client.post.return_value = mock_token_response
            mock_client.get.return_value = mock_userinfo_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_httpx.return_value = mock_client

            response = client.get(f"/auth/callback/?code=test-code&state={state}")

        assert response.status_code == 302

        # Verify groups updated
        user_groups = UserGroups.objects.get(user=user)
        assert "WCComps_GoldTeam" in user_groups.groups
        assert "NewGroup" in user_groups.groups
        assert "OldGroup" not in user_groups.groups  # Old groups replaced

    def test_callback_handles_username_change(self, oauth_state_session):
        """Callback should update username if changed in Authentik."""
        client, state = oauth_state_session

        # Create existing user with old username
        user = User.objects.create_user(username="oldusername")
        UserGroups.objects.create(
            user=user,
            authentik_id="user-authentik-id",
            groups=["SomeGroup"],
        )

        mock_token_response = MagicMock()
        mock_token_response.json.return_value = {"access_token": "test-token"}
        mock_token_response.raise_for_status = MagicMock()

        mock_userinfo_response = MagicMock()
        mock_userinfo_response.json.return_value = {
            "sub": "user-authentik-id",
            "preferred_username": "newusername",  # Username changed
            "groups": ["SomeGroup"],
        }
        mock_userinfo_response.raise_for_status = MagicMock()

        with (
            patch("core.oauth._get_oauth_config") as mock_config,
            patch("core.oauth.httpx.Client") as mock_httpx,
        ):
            mock_config.return_value = {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "authorization_endpoint": "https://auth.example.com/authorize/",
                "token_endpoint": "https://auth.example.com/token/",
                "userinfo_endpoint": "https://auth.example.com/userinfo/",
                "end_session_endpoint": "https://auth.example.com/end-session/",
            }
            mock_client = MagicMock()
            mock_client.post.return_value = mock_token_response
            mock_client.get.return_value = mock_userinfo_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_httpx.return_value = mock_client

            response = client.get(f"/auth/callback/?code=test-code&state={state}")

        assert response.status_code == 302

        # Verify username updated
        user.refresh_from_db()
        assert user.username == "newusername"

    def test_callback_rejects_invalid_state(self):
        """Callback should reject request with invalid state."""
        client = Client()
        # Set up session with different state
        session = client.session
        session["oauth_pending_states"] = [
            {"state": "correct-state", "created": "2025-01-01T00:00:00+00:00", "next": "/"},
        ]
        session.save()

        response = client.get("/auth/callback/?code=test-code&state=wrong-state")

        assert response.status_code == 200  # Error page
        assert b"Security Error" in response.content

    def test_callback_rejects_missing_state(self):
        """Callback should reject request without state parameter."""
        client = Client()
        response = client.get("/auth/callback/?code=test-code")

        assert response.status_code == 200  # Error page
        assert b"Session Expired" in response.content

    def test_callback_rejects_expired_state(self, oauth_state_session):
        """Callback should reject expired state (>5 minutes)."""
        client, state = oauth_state_session

        # Set state creation time to 10 minutes ago
        session = client.session
        from datetime import timedelta

        from django.utils import timezone

        old_time = timezone.now() - timedelta(minutes=10)
        session["oauth_pending_states"] = [
            {"state": state, "created": old_time.isoformat(), "next": "/"},
        ]
        session.save()

        response = client.get(f"/auth/callback/?code=test-code&state={state}")

        assert response.status_code == 200  # Error page
        assert b"Session Expired" in response.content

    def test_callback_handles_access_denied(self):
        """Callback should handle user cancelling login."""
        client = Client()
        response = client.get("/auth/callback/?error=access_denied")

        assert response.status_code == 200
        assert b"Login Cancelled" in response.content

    def test_callback_logs_user_in(self, oauth_state_session):
        """Callback should log the user in after successful auth."""
        client, state = oauth_state_session

        mock_token_response = MagicMock()
        mock_token_response.json.return_value = {"access_token": "test-token"}
        mock_token_response.raise_for_status = MagicMock()

        mock_userinfo_response = MagicMock()
        mock_userinfo_response.json.return_value = {
            "sub": "login-test-id",
            "preferred_username": "loginuser",
            "groups": [],
        }
        mock_userinfo_response.raise_for_status = MagicMock()

        with (
            patch("core.oauth._get_oauth_config") as mock_config,
            patch("core.oauth.httpx.Client") as mock_httpx,
        ):
            mock_config.return_value = {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "authorization_endpoint": "https://auth.example.com/authorize/",
                "token_endpoint": "https://auth.example.com/token/",
                "userinfo_endpoint": "https://auth.example.com/userinfo/",
                "end_session_endpoint": "https://auth.example.com/end-session/",
            }
            mock_client = MagicMock()
            mock_client.post.return_value = mock_token_response
            mock_client.get.return_value = mock_userinfo_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_httpx.return_value = mock_client

            client.get(f"/auth/callback/?code=test-code&state={state}")

        # Check user is logged in
        user = User.objects.get(username="loginuser")
        assert "_auth_user_id" in client.session
        assert str(user.id) == client.session["_auth_user_id"]

    def test_callback_redirects_to_next_url(self, oauth_state_session):
        """Callback should redirect to stored next URL."""
        client, state = oauth_state_session

        # Set next URL in the pending state entry
        session = client.session
        pending = session.get("oauth_pending_states", [])
        if pending:
            pending[0]["next"] = "/my-dashboard/"
            session["oauth_pending_states"] = pending
        session.save()

        mock_token_response = MagicMock()
        mock_token_response.json.return_value = {"access_token": "test-token"}
        mock_token_response.raise_for_status = MagicMock()

        mock_userinfo_response = MagicMock()
        mock_userinfo_response.json.return_value = {
            "sub": "redirect-test-id",
            "preferred_username": "redirectuser",
            "groups": [],
        }
        mock_userinfo_response.raise_for_status = MagicMock()

        with (
            patch("core.oauth._get_oauth_config") as mock_config,
            patch("core.oauth.httpx.Client") as mock_httpx,
        ):
            mock_config.return_value = {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "authorization_endpoint": "https://auth.example.com/authorize/",
                "token_endpoint": "https://auth.example.com/token/",
                "userinfo_endpoint": "https://auth.example.com/userinfo/",
                "end_session_endpoint": "https://auth.example.com/end-session/",
            }
            mock_client = MagicMock()
            mock_client.post.return_value = mock_token_response
            mock_client.get.return_value = mock_userinfo_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_httpx.return_value = mock_client

            response = client.get(f"/auth/callback/?code=test-code&state={state}")

        assert response.status_code == 302
        assert response.url == "/my-dashboard/"


@pytest.mark.django_db
class TestOAuthLogout:
    """Test OAuth logout."""

    def test_logout_clears_session(self):
        """Logout should clear Django session."""
        client = Client()
        user = User.objects.create_user(username="logoutuser")
        client.force_login(user)

        # Verify logged in
        assert "_auth_user_id" in client.session

        with patch("core.oauth._get_oauth_config") as mock_config:
            mock_config.return_value = {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "authorization_endpoint": "https://auth.example.com/authorize/",
                "token_endpoint": "https://auth.example.com/token/",
                "userinfo_endpoint": "https://auth.example.com/userinfo/",
                "end_session_endpoint": "https://auth.example.com/end-session/",
            }
            client.get("/auth/logout/")

        # Verify logged out
        assert "_auth_user_id" not in client.session

    def test_logout_redirects_to_authentik(self):
        """Logout should redirect to Authentik end-session endpoint."""
        client = Client()
        user = User.objects.create_user(username="logoutuser2")
        client.force_login(user)

        with patch("core.oauth._get_oauth_config") as mock_config:
            mock_config.return_value = {
                "client_id": "test-client-id",
                "client_secret": "test-secret",
                "authorization_endpoint": "https://auth.example.com/authorize/",
                "token_endpoint": "https://auth.example.com/token/",
                "userinfo_endpoint": "https://auth.example.com/userinfo/",
                "end_session_endpoint": "https://auth.example.com/end-session/",
            }
            response = client.get("/auth/logout/")

        assert response.status_code == 302
        assert "auth.example.com/end-session" in response.url
