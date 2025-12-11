"""Shared pytest fixtures for all web tests."""

from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.test import Client

from core.models import UserGroups
from team.models import DiscordLink


@pytest.fixture
def create_user_with_groups(db: Any) -> Callable[..., User]:
    """Factory fixture to create users with Authentik groups and DiscordLink."""
    _discord_id_counter = [1000000000]

    def _create(username: str, groups: list[str], is_staff: bool = False) -> User:
        user = User.objects.create_user(username=username, password="testpass123", is_staff=is_staff)
        UserGroups.objects.create(
            user=user,
            authentik_id=f"{username}-uid",
            groups=groups,
        )
        # Also create DiscordLink for ticketing users
        DiscordLink.objects.create(
            user=user,
            discord_id=_discord_id_counter[0],
            discord_username=username,
            is_active=True,
        )
        _discord_id_counter[0] += 1
        return user

    return _create


@pytest.fixture
def unauthenticated_client() -> Client:
    """Create an unauthenticated Django test client."""
    return Client()


@pytest.fixture
def blue_team_user(create_user_with_groups: Callable[..., User]) -> User:
    """Create a Blue Team user."""
    return create_user_with_groups("blueteam01", ["WCComps_BlueTeam01"])


@pytest.fixture
def blue_team_02_user(create_user_with_groups: Callable[..., User]) -> User:
    """Create a second Blue Team user."""
    return create_user_with_groups("blueteam02", ["WCComps_BlueTeam02"])


@pytest.fixture
def red_team_user(create_user_with_groups: Callable[..., User]) -> User:
    """Create a Red Team user."""
    return create_user_with_groups("redteam", ["WCComps_RedTeam"])


@pytest.fixture
def gold_team_user(create_user_with_groups: Callable[..., User]) -> User:
    """Create a Gold Team user."""
    return create_user_with_groups("goldteam", ["WCComps_GoldTeam"])


@pytest.fixture
def white_team_user(create_user_with_groups: Callable[..., User]) -> User:
    """Create a White Team user."""
    return create_user_with_groups("whiteteam", ["WCComps_WhiteTeam"])


@pytest.fixture
def orange_team_user(create_user_with_groups: Callable[..., User]) -> User:
    """Create an Orange Team user."""
    return create_user_with_groups("orangeteam", ["WCComps_OrangeTeam"])


@pytest.fixture
def ticketing_support_user(create_user_with_groups: Callable[..., User]) -> User:
    """Create a Ticketing Support user."""
    return create_user_with_groups("support", ["WCComps_Ticketing_Support"])


@pytest.fixture
def ticketing_admin_user(create_user_with_groups: Callable[..., User]) -> User:
    """Create a Ticketing Admin user."""
    return create_user_with_groups("ticketing_admin", ["WCComps_Ticketing_Admin"])


@pytest.fixture
def admin_user(create_user_with_groups: Callable[..., User]) -> User:
    """Create an admin user (is_staff + Discord_Admin group)."""
    return create_user_with_groups("admin", ["WCComps_Discord_Admin"], is_staff=True)


@pytest.fixture(autouse=True)
def reset_quotient_client_cache():
    """Reset the QuotientClient LRU cache before each test for proper isolation."""
    from quotient.client import get_quotient_client

    get_quotient_client.cache_clear()
    yield
    get_quotient_client.cache_clear()


@pytest.fixture(autouse=True)
def reset_has_permission_reference():
    """
    Reset scoring.views.has_permission to the real function after each test.

    This fixes test isolation issues where @patch("core.auth_utils.has_permission")
    in one test module pollutes the reference in scoring.views.
    """
    yield
    # After test, ensure scoring.views.has_permission points to the real function
    import scoring.views

    from core import auth_utils

    scoring.views.has_permission = auth_utils.has_permission


@pytest.fixture
def mock_quotient_client():
    """Mock Quotient client to avoid API errors in tests."""
    with patch("quotient.client.QuotientClient") as mock_client:
        instance = MagicMock()
        instance.get_infrastructure.return_value = None
        instance.get_injects.return_value = []
        instance.get_scores.return_value = []
        mock_client.return_value = instance
        yield instance
