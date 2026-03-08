"""Tests for AuthentikManager update_user_discord_id method."""

from unittest.mock import MagicMock, patch

import pytest
import requests

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

    def test_headers_contain_bearer_token(self, manager):
        """Headers should contain Bearer token."""
        assert manager.headers["Authorization"] == "Bearer test-token"
        assert manager.headers["Content-Type"] == "application/json"


class TestUpdateUserDiscordId:
    """Tests for update_user_discord_id method."""

    @pytest.fixture
    def manager(self):
        """Create AuthentikManager with mocked settings."""
        with patch("core.authentik_manager.settings") as mock_settings:
            mock_settings.AUTHENTIK_URL = "https://auth.example.com"
            mock_settings.AUTHENTIK_TOKEN = "test-token"
            return AuthentikManager()

    @patch("core.authentik_manager.requests.get")
    @patch("core.authentik_manager.requests.patch")
    def test_updates_user_with_discord_id(self, mock_patch, mock_get, manager):
        """Should update user attributes with discord_id."""
        # Mock GET response (existing user)
        mock_get_response = MagicMock()
        mock_get_response.json.return_value = {
            "pk": "user-uuid-123",
            "attributes": {"existing_attr": "value"},
        }
        mock_get.return_value = mock_get_response

        # Mock PATCH response
        mock_patch_response = MagicMock()
        mock_patch_response.json.return_value = {"pk": "user-uuid-123"}
        mock_patch.return_value = mock_patch_response

        result = manager.update_user_discord_id("user-uuid-123", 123456789)

        assert result is True

        # Verify GET was called to fetch current user
        mock_get.assert_called_once()
        assert "user-uuid-123" in mock_get.call_args[0][0]

        # Verify PATCH was called with merged attributes
        mock_patch.assert_called_once()
        call_kwargs = mock_patch.call_args[1]
        assert call_kwargs["json"]["attributes"]["discord_id"] == "123456789"
        assert call_kwargs["json"]["attributes"]["existing_attr"] == "value"

    @patch("core.authentik_manager.requests.get")
    @patch("core.authentik_manager.requests.patch")
    def test_preserves_existing_attributes(self, mock_patch, mock_get, manager):
        """Should preserve existing user attributes when adding discord_id."""
        mock_get_response = MagicMock()
        mock_get_response.json.return_value = {
            "pk": "user-uuid",
            "attributes": {"role": "admin", "team": "gold"},
        }
        mock_get.return_value = mock_get_response

        mock_patch_response = MagicMock()
        mock_patch_response.json.return_value = {}
        mock_patch.return_value = mock_patch_response

        manager.update_user_discord_id("user-uuid", 999999999)

        call_kwargs = mock_patch.call_args[1]
        attrs = call_kwargs["json"]["attributes"]
        assert attrs["role"] == "admin"
        assert attrs["team"] == "gold"
        assert attrs["discord_id"] == "999999999"

    @patch("core.authentik_manager.requests.get")
    def test_raises_on_403_error(self, mock_get, manager):
        """Should raise on 403 Forbidden (permission issue)."""
        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Permission denied"
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)
        mock_get.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            manager.update_user_discord_id("user-uuid", 123456789)

    @patch("core.authentik_manager.requests.get")
    def test_raises_on_other_http_errors(self, mock_get, manager):
        """Should raise on other HTTP errors."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Server error"
        mock_response.raise_for_status.side_effect = requests.HTTPError(response=mock_response)
        mock_get.return_value = mock_response

        with pytest.raises(requests.HTTPError):
            manager.update_user_discord_id("user-uuid", 123456789)
