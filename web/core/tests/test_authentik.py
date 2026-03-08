"""Tests for AuthentikManager update_user_discord_id method."""

from unittest.mock import MagicMock, Mock, patch

import pytest
import httpx

from core.authentik_manager import AuthentikManager


class TestAuthentikManager:
    """Tests for AuthentikManager class."""

    @pytest.fixture
    def manager(self):
        """Create AuthentikManager with mocked settings."""
        with patch("core.authentik_manager.settings") as mock_settings:
            mock_settings.AUTHENTIK_URL = "https://auth.example.com"
            mock_settings.AUTHENTIK_TOKEN = "test-token"
            return AuthentikManager()

    def test_init_sets_base_url_and_token(self, manager):
        """Manager should initialize with base URL and token from settings."""
        assert manager.base_url == "https://auth.example.com"
        assert manager.token == "test-token"

    def test_client_headers_contain_bearer_token(self, manager):
        """Client headers should contain Bearer token."""
        assert manager.client.headers["Authorization"] == "Bearer test-token"
        assert manager.client.headers["Content-Type"] == "application/json"


class TestUpdateUserDiscordId:
    """Tests for update_user_discord_id method."""

    @pytest.fixture
    def manager(self):
        """Create AuthentikManager with mocked client."""
        with patch("core.authentik_manager.settings") as mock_settings:
            mock_settings.AUTHENTIK_URL = "https://auth.example.com"
            mock_settings.AUTHENTIK_TOKEN = "test-token"
            mgr = AuthentikManager()
            mgr.client = Mock()
            return mgr

    def test_updates_user_with_discord_id(self, manager):
        """Should update user attributes with discord_id."""
        # Mock GET response (existing user)
        mock_get_response = MagicMock()
        mock_get_response.json.return_value = {
            "pk": "user-uuid-123",
            "attributes": {"existing_attr": "value"},
        }
        manager.client.get.return_value = mock_get_response

        # Mock PATCH response
        mock_patch_response = MagicMock()
        manager.client.patch.return_value = mock_patch_response

        result = manager.update_user_discord_id("user-uuid-123", 123456789)

        assert result is True

        # Verify GET was called to fetch current user
        manager.client.get.assert_called_once()
        assert "user-uuid-123" in manager.client.get.call_args[0][0]

        # Verify PATCH was called with merged attributes
        manager.client.patch.assert_called_once()
        call_kwargs = manager.client.patch.call_args[1]
        assert call_kwargs["json"]["attributes"]["discord_id"] == "123456789"
        assert call_kwargs["json"]["attributes"]["existing_attr"] == "value"

    def test_preserves_existing_attributes(self, manager):
        """Should preserve existing user attributes when adding discord_id."""
        mock_get_response = MagicMock()
        mock_get_response.json.return_value = {
            "pk": "user-uuid",
            "attributes": {"role": "admin", "team": "gold"},
        }
        manager.client.get.return_value = mock_get_response
        manager.client.patch.return_value = MagicMock()

        manager.update_user_discord_id("user-uuid", 999999999)

        call_kwargs = manager.client.patch.call_args[1]
        attrs = call_kwargs["json"]["attributes"]
        assert attrs["role"] == "admin"
        assert attrs["team"] == "gold"
        assert attrs["discord_id"] == "999999999"

    def test_raises_on_403_error(self, manager):
        """Should raise on 403 Forbidden (permission issue)."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Permission denied"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_response
        )
        manager.client.get.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            manager.update_user_discord_id("user-uuid", 123456789)

    def test_raises_on_other_http_errors(self, manager):
        """Should raise on other HTTP errors."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=mock_response
        )
        manager.client.get.return_value = mock_response

        with pytest.raises(httpx.HTTPStatusError):
            manager.update_user_discord_id("user-uuid", 123456789)
