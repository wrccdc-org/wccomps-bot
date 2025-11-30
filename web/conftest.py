"""Shared pytest fixtures for all web tests."""

from collections.abc import Callable
from typing import Any

import pytest
from allauth.socialaccount.models import SocialAccount, SocialApp
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.test import Client


@pytest.fixture
def social_app(db: Any) -> SocialApp:
    """Set up SocialApp for Authentik provider."""
    site = Site.objects.get_current()
    app, _ = SocialApp.objects.get_or_create(
        provider="authentik",
        name="Authentik",
        defaults={"client_id": "test-client-id", "secret": "test-secret"},
    )
    app.sites.add(site)
    return app


@pytest.fixture
def create_user_with_groups(db: Any, social_app: SocialApp) -> Callable[..., User]:
    """Factory fixture to create users with Authentik groups."""

    def _create(username: str, groups: list[str], is_staff: bool = False) -> User:
        user = User.objects.create_user(username=username, password="testpass123", is_staff=is_staff)  # noqa: S106
        SocialAccount.objects.create(
            user=user,
            provider="authentik",
            uid=f"{username}-uid",
            extra_data={
                "userinfo": {
                    "groups": groups,
                    "preferred_username": username,
                },
            },
        )
        if hasattr(user, "person"):
            user.person.refresh_from_authentik()
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
