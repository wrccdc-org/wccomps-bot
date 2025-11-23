"""Tests for Authentik API manager."""

from unittest.mock import Mock, patch

import pytest
import requests
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from bot.authentik_manager import AuthentikAPIError, AuthentikManager


class TestAuthentikAPIError:
    """Test AuthentikAPIError exception class."""

    def test_error_with_all_fields(self) -> None:
        """Test error message formatting with all fields present."""
        error = AuthentikAPIError(
            message="Test error",
            status_code=404,
            response_text="Resource not found",
            url="https://auth.example.com/api/v3/test",
        )
        formatted = error.formatted_message()
        assert "Test error" in formatted
        assert "Status: 404" in formatted
        assert "Resource not found" in formatted
        assert "https://auth.example.com" in formatted

    def test_error_with_minimal_fields(self) -> None:
        """Test error message formatting with only required field."""
        error = AuthentikAPIError(message="Simple error")
        formatted = error.formatted_message()
        assert formatted == "Simple error"

    @given(
        message=st.text(min_size=1, max_size=100),
        status_code=st.integers(min_value=100, max_value=599),
    )
    @settings(max_examples=50)
    def test_error_message_property(self, message: str, status_code: int) -> None:
        """Property: error message always contains the original message."""
        error = AuthentikAPIError(message=message, status_code=status_code)
        assert message in str(error)
        assert f"Status: {status_code}" in str(error)


@pytest.mark.django_db
class TestAuthentikManager:
    """Test AuthentikManager class."""

    @pytest.fixture
    def manager(self) -> AuthentikManager:
        """Create AuthentikManager instance."""
        with patch("bot.authentik_manager.settings") as mock_settings:
            mock_settings.AUTHENTIK_URL = "https://auth.test.local"
            mock_settings.AUTHENTIK_TOKEN = "test-token-123"
            return AuthentikManager()

    def test_handle_response_error_401(self, manager: AuthentikManager) -> None:
        """Test error handling for 401 Unauthorized."""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.url = "https://auth.test.local/api/v3/test"
        mock_response.text = "Unauthorized"
        mock_response.json.side_effect = Exception("Not JSON")

        error = manager._handle_response_error(mock_response, "Test context")

        assert error.status_code == 401
        assert "Authentication failed" in str(error)
        assert "check AUTHENTIK_TOKEN" in str(error)

    def test_handle_response_error_403(self, manager: AuthentikManager) -> None:
        """Test error handling for 403 Forbidden."""
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.url = "https://auth.test.local/api/v3/test"
        mock_response.json.return_value = {"detail": "Permission denied"}

        error = manager._handle_response_error(mock_response, "Test operation")

        assert error.status_code == 403
        assert "Permission denied" in str(error)
        assert "token lacks required permissions" in str(error)

    def test_handle_response_error_404(self, manager: AuthentikManager) -> None:
        """Test error handling for 404 Not Found."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.url = "https://auth.test.local/api/v3/test"
        mock_response.text = "Not found"
        mock_response.json.side_effect = Exception("Not JSON")

        error = manager._handle_response_error(mock_response, "Find resource")

        assert error.status_code == 404
        assert "Resource not found" in str(error)

    @given(status_code=st.integers(min_value=500, max_value=599))
    @settings(max_examples=20)
    def test_handle_response_error_5xx(self, status_code: int) -> None:
        """Property: 5xx errors are handled consistently."""
        with patch("bot.authentik_manager.settings") as mock_settings:
            mock_settings.AUTHENTIK_URL = "https://auth.test.local"
            mock_settings.AUTHENTIK_TOKEN = "test-token-123"
            manager = AuthentikManager()

            mock_response = Mock()
            mock_response.status_code = status_code
            mock_response.url = "https://auth.test.local/api/v3/test"
            mock_response.text = "Server error"
            mock_response.json.side_effect = Exception("Not JSON")

            error = manager._handle_response_error(mock_response, "Server operation")

            assert error.status_code == status_code
            assert "Server operation" in str(error)

    def test_get_application_by_slug_success(self, manager: AuthentikManager) -> None:
        """Test successful application retrieval by slug."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "results": [
                {
                    "pk": "app-123",
                    "slug": "netbird",
                    "name": "NetBird VPN",
                }
            ]
        }

        with patch("requests.get", return_value=mock_response) as mock_get:
            mock_response.raise_for_status = Mock()
            app = manager.get_application_by_slug("netbird")

            assert app is not None
            assert app["pk"] == "app-123"
            assert app["slug"] == "netbird"
            mock_get.assert_called_once()

    def test_get_application_by_slug_not_found(self, manager: AuthentikManager) -> None:
        """Test application not found returns None."""
        mock_response = Mock()
        mock_response.json.return_value = {"results": []}

        with patch("requests.get", return_value=mock_response):
            mock_response.raise_for_status = Mock()
            app = manager.get_application_by_slug("nonexistent")

            assert app is None

    def test_get_application_by_slug_http_error(self, manager: AuthentikManager) -> None:
        """Test HTTP error handling during application retrieval."""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.url = "https://auth.test.local/api/v3/core/applications/"
        mock_response.text = "Internal server error"
        mock_response.json.side_effect = Exception("Not JSON")

        with patch("requests.get", return_value=mock_response) as mock_get:
            mock_response.raise_for_status = Mock(side_effect=requests.exceptions.HTTPError(response=mock_response))
            app = manager.get_application_by_slug("test-app")

            assert app is None
            mock_get.assert_called_once()

    def test_get_application_by_slug_network_error(self, manager: AuthentikManager) -> None:
        """Test network error handling during application retrieval."""
        with patch(
            "requests.get",
            side_effect=requests.exceptions.ConnectionError("Connection refused"),
        ):
            app = manager.get_application_by_slug("test-app")

            assert app is None

    def test_get_blueteam_binding_success(self, manager: AuthentikManager) -> None:
        """Test successful BlueTeam binding retrieval."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "results": [
                {
                    "pk": "binding-123",
                    "group": "group-456",
                    "group_obj": {"name": "WCComps_BlueTeam", "pk": "group-456"},
                    "enabled": True,
                }
            ]
        }

        with patch("requests.get", return_value=mock_response):
            mock_response.raise_for_status = Mock()
            binding, error = manager.get_blueteam_binding("app-123")

            assert binding is not None
            assert error is None
            assert binding["pk"] == "binding-123"
            assert "blueteam" in binding["group_obj"]["name"].lower()

    def test_get_blueteam_binding_not_found(self, manager: AuthentikManager) -> None:
        """Test BlueTeam binding not found."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "results": [
                {
                    "pk": "binding-123",
                    "group": "group-789",
                    "group_obj": {"name": "WCComps_GoldTeam", "pk": "group-789"},
                }
            ]
        }

        with patch("requests.get", return_value=mock_response):
            mock_response.raise_for_status = Mock()
            binding, error = manager.get_blueteam_binding("app-123")

            assert binding is None
            assert error is not None
            assert "No BlueTeam group binding found" in error

    def test_get_blueteam_binding_empty_results(self, manager: AuthentikManager) -> None:
        """Test BlueTeam binding with no results."""
        mock_response = Mock()
        mock_response.json.return_value = {"results": []}

        with patch("requests.get", return_value=mock_response):
            mock_response.raise_for_status = Mock()
            binding, error = manager.get_blueteam_binding("app-123")

            assert binding is None
            assert error is not None
            assert "No BlueTeam group binding found" in error

    def test_get_blueteam_group_success(self, manager: AuthentikManager) -> None:
        """Test successful BlueTeam group PK retrieval."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "results": [
                {
                    "group": "group-blueteam-123",
                    "group_obj": {"name": "WCComps_BlueTeam"},
                }
            ]
        }

        with patch("requests.get", return_value=mock_response):
            mock_response.raise_for_status = Mock()
            group_pk, error = manager.get_blueteam_group("app-123")

            assert group_pk == "group-blueteam-123"
            assert error is None

    def test_get_blueteam_group_not_found(self, manager: AuthentikManager) -> None:
        """Test BlueTeam group not found."""
        mock_response = Mock()
        mock_response.json.return_value = {"results": []}

        with patch("requests.get", return_value=mock_response):
            mock_response.raise_for_status = Mock()
            group_pk, error = manager.get_blueteam_group("app-123")

            assert group_pk is None
            assert error is not None
            assert "No BlueTeam group found" in error

    def test_find_blueteam_group_from_first_app(self, manager: AuthentikManager) -> None:
        """Test finding BlueTeam group from first application."""
        app_slugs = ["netbird", "scoring", "vault"]

        # Mock get_application_by_slug to return app for first slug
        with (
            patch.object(manager, "get_application_by_slug") as mock_get_app,
            patch.object(manager, "get_blueteam_group") as mock_get_group,
        ):
            mock_get_app.return_value = {"pk": "app-netbird"}
            mock_get_group.return_value = ("group-blueteam-123", None)

            group_pk, error = manager.find_blueteam_group_from_any_app(app_slugs)

            assert group_pk == "group-blueteam-123"
            assert error is None
            mock_get_app.assert_called_once_with("netbird")

    def test_find_blueteam_group_from_second_app(self, manager: AuthentikManager) -> None:
        """Test finding BlueTeam group from second application."""
        app_slugs = ["netbird", "scoring", "vault"]

        with (
            patch.object(manager, "get_application_by_slug") as mock_get_app,
            patch.object(manager, "get_blueteam_group") as mock_get_group,
        ):
            # First app exists but no group, second app has group
            mock_get_app.side_effect = [{"pk": "app-netbird"}, {"pk": "app-scoring"}]
            mock_get_group.side_effect = [
                (None, "Not found"),
                ("group-blueteam-123", None),
            ]

            group_pk, error = manager.find_blueteam_group_from_any_app(app_slugs)

            assert group_pk == "group-blueteam-123"
            assert error is None

    def test_find_blueteam_group_not_found_any_app(self, manager: AuthentikManager) -> None:
        """Test BlueTeam group not found in any application."""
        app_slugs = ["netbird", "scoring"]

        with (
            patch.object(manager, "get_application_by_slug") as mock_get_app,
            patch.object(manager, "get_blueteam_group") as mock_get_group,
        ):
            mock_get_app.side_effect = [{"pk": "app-1"}, {"pk": "app-2"}]
            mock_get_group.return_value = (None, "Not found")

            group_pk, error = manager.find_blueteam_group_from_any_app(app_slugs)

            assert group_pk is None
            assert error is not None
            assert "Could not find BlueTeam group" in error

    def test_update_binding_enabled_success(self, manager: AuthentikManager) -> None:
        """Test successfully updating binding enabled state."""
        binding = {
            "pk": "binding-123",
            "group": "group-456",
            "enabled": False,
        }

        mock_response = Mock()
        mock_response.raise_for_status = Mock()

        with patch("requests.put", return_value=mock_response) as mock_put:
            result = manager.update_binding_enabled(binding, True)

            assert result is True
            mock_put.assert_called_once()
            call_args = mock_put.call_args
            assert call_args[1]["json"]["enabled"] is True

    def test_update_binding_enabled_failure(self, manager: AuthentikManager) -> None:
        """Test binding update failure handling."""
        binding = {"pk": "binding-123", "enabled": False}

        with patch(
            "requests.put",
            side_effect=requests.exceptions.ConnectionError("Network error"),
        ):
            result = manager.update_binding_enabled(binding, True)

            assert result is False

    def test_enable_application_success(self, manager: AuthentikManager) -> None:
        """Test successfully enabling an application."""
        with (
            patch.object(manager, "get_application_by_slug") as mock_get_app,
            patch.object(manager, "get_blueteam_binding") as mock_get_binding,
            patch.object(manager, "update_binding_enabled") as mock_update,
        ):
            mock_get_app.return_value = {"pk": "app-123", "slug": "netbird"}
            mock_get_binding.return_value = (
                {"pk": "binding-456", "enabled": True},
                None,
            )
            mock_update.return_value = True

            success, error = manager.enable_application("netbird")

            assert success is True
            assert error is None
            # Check that update_binding_enabled was called with enabled=False
            mock_update.assert_called_once()
            call_args = mock_update.call_args
            assert call_args[0][0] == {"pk": "binding-456", "enabled": True}
            assert call_args[1]["enabled"] is False

    def test_enable_application_not_found(self, manager: AuthentikManager) -> None:
        """Test enabling non-existent application."""
        with patch.object(manager, "get_application_by_slug") as mock_get_app:
            mock_get_app.return_value = None

            success, error = manager.enable_application("nonexistent")

            assert success is False
            assert error is not None
            assert "not found" in error

    def test_enable_application_no_binding(self, manager: AuthentikManager) -> None:
        """Test enabling application with no BlueTeam binding."""
        with (
            patch.object(manager, "get_application_by_slug") as mock_get_app,
            patch.object(manager, "get_blueteam_binding") as mock_get_binding,
        ):
            mock_get_app.return_value = {"pk": "app-123"}
            mock_get_binding.return_value = (None, "No binding found")

            success, error = manager.enable_application("test-app")

            assert success is False
            assert error is not None
            assert "No binding found" in error

    def test_disable_application_success(self, manager: AuthentikManager) -> None:
        """Test successfully disabling an application."""
        with (
            patch.object(manager, "get_application_by_slug") as mock_get_app,
            patch.object(manager, "get_blueteam_binding") as mock_get_binding,
            patch.object(manager, "update_binding_enabled") as mock_update,
        ):
            mock_get_app.return_value = {"pk": "app-123"}
            mock_get_binding.return_value = (
                {"pk": "binding-456", "enabled": False},
                None,
            )
            mock_update.return_value = True

            success, error = manager.disable_application("netbird")

            assert success is True
            assert error is None
            # Check that update_binding_enabled was called with enabled=True
            mock_update.assert_called_once()
            call_args = mock_update.call_args
            assert call_args[0][0] == {"pk": "binding-456", "enabled": False}
            assert call_args[1]["enabled"] is True

