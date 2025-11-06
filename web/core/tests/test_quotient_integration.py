"""Tests for Quotient API integration."""

from typing import Any, Dict
import pytest
from unittest.mock import Mock, patch
from quotient.client import (
    QuotientClient,
    QuotientAPIError,
)


@pytest.fixture
def mock_infrastructure() -> Dict[str, Any]:
    """Create mock infrastructure data."""
    return {
        "boxes": [
            {
                "name": "web01",
                "ip": "10.0.1.10",
                "services": [
                    {"name": "http", "display_name": "HTTP", "type": "web"},
                    {"name": "ssh", "display_name": "SSH", "type": "ssh"},
                ],
            },
            {
                "name": "db01",
                "ip": "10.0.1.20",
                "services": [
                    {
                        "name": "postgres",
                        "display_name": "PostgreSQL",
                        "type": "custom",
                    },
                ],
            },
        ],
        "event_name": "Test Competition",
        "team_count": 10,
        "api_version": "v1",
    }


class TestQuotientClient:
    """Test QuotientClient class."""

    def test_get_infrastructure_success(
        self, mock_infrastructure: Dict[str, Any]
    ) -> None:
        """Test successful infrastructure fetch."""
        client = QuotientClient(
            base_url="http://test.local",
            admin_username="admin",
            admin_password="password",
        )

        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = mock_infrastructure
        mock_session.get.return_value = mock_response
        client.session = mock_session

        infrastructure = client.get_infrastructure(force_refresh=True)

        assert infrastructure is not None
        assert len(infrastructure.boxes) == 2
        assert infrastructure.boxes[0].name == "web01"
        assert infrastructure.boxes[0].ip == "10.0.1.10"
        assert len(infrastructure.boxes[0].services) == 2
        assert infrastructure.boxes[0].services[0].name == "http"
        assert infrastructure.event_name == "Test Competition"

    def test_get_service_choices(self, mock_infrastructure: Dict[str, Any]) -> None:
        """Test service choices generation."""
        client = QuotientClient(base_url="http://test.local")

        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = mock_infrastructure
        mock_session.get.return_value = mock_response
        client.session = mock_session

        choices = client.get_service_choices()

        assert len(choices) == 3
        assert choices[0]["value"] == "db01:postgres"
        assert choices[0]["label"] == "db01 - PostgreSQL"
        assert choices[0]["box_ip"] == "10.0.1.20"
        assert choices[0]["service_type"] == "custom"

    def test_get_box_names(self, mock_infrastructure: Dict[str, Any]) -> None:
        """Test box names list generation."""
        client = QuotientClient(base_url="http://test.local")

        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = mock_infrastructure
        mock_session.get.return_value = mock_response
        client.session = mock_session

        box_names = client.get_box_names()

        assert len(box_names) == 2
        assert "web01" in box_names
        assert "db01" in box_names

    def test_authentication_failure(self) -> None:
        """Test authentication failure handling."""
        client = QuotientClient(
            base_url="http://test.local",
            admin_username="bad",
            admin_password="wrong",
        )

        with patch("core.quotient_client.requests.Session") as mock_session_class:
            mock_session = Mock()
            mock_response = Mock()
            # Wrap the exception properly in requests.RequestException
            from requests import RequestException

            mock_response.raise_for_status.side_effect = RequestException("Auth failed")
            mock_session.post.return_value = mock_response
            mock_session_class.return_value = mock_session

            with pytest.raises(QuotientAPIError, match="Authentication failed"):
                client._get_session()

    def test_get_infrastructure_api_error(self) -> None:
        """Test API error handling during infrastructure fetch."""
        from requests import RequestException

        client = QuotientClient(base_url="http://test.local")

        mock_session = Mock()
        # Simulate network error with RequestException
        mock_session.get.side_effect = RequestException("Network error")
        client.session = mock_session

        infrastructure = client.get_infrastructure(force_refresh=True)

        assert infrastructure is None

    def test_caching(self, mock_infrastructure: Dict[str, Any]) -> None:
        """Test that infrastructure is cached."""
        client = QuotientClient(base_url="http://test.local", cache_ttl=60)

        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = mock_infrastructure
        mock_session.get.return_value = mock_response
        client.session = mock_session

        with patch("core.quotient_client.cache") as mock_cache:
            mock_cache.get.return_value = None

            # First call - should hit API
            infrastructure1 = client.get_infrastructure()
            assert mock_session.get.called
            assert mock_cache.set.called

            # Reset mocks
            mock_session.get.reset_mock()
            mock_cache.set.reset_mock()

            # Second call - should use cache
            mock_cache.get.return_value = infrastructure1
            infrastructure2 = client.get_infrastructure()
            assert infrastructure2 == infrastructure1
            assert not mock_session.get.called
            assert not mock_cache.set.called
