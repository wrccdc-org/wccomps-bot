"""Browser test fixtures: Playwright + session injection, no OAuth required."""

import pytest
from django.test import Client
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from core.models import UserGroups
from team.models import DiscordLink, Team

# Role name → Authentik group(s)
ROLE_GROUPS: dict[str, list[str]] = {
    "blue_team": ["WCComps_BlueTeam01"],
    "red_team": ["WCComps_RedTeam"],
    "gold_team": ["WCComps_GoldTeam"],
    "orange_team": ["WCComps_OrangeTeam"],
    "white_team": ["WCComps_WhiteTeam"],
    "ticketing_support": ["WCComps_Ticketing_Support"],
    "ticketing_admin": ["WCComps_Ticketing_Admin"],
    "admin": ["WCComps_Discord_Admin"],
}

ALL_ROLES = [*ROLE_GROUPS.keys(), "unauthenticated"]


@pytest.fixture(scope="session")
def pw_browser():
    """Launch a single Chromium instance for the whole test session."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def _create_role_user(role: str, db) -> "User | None":
    """Create a test user with the given role's Authentik groups + DiscordLink."""
    from django.contrib.auth.models import User

    if role == "unauthenticated":
        return None

    groups = ROLE_GROUPS[role]
    username = f"browser_test_{role}"
    user = User.objects.create_user(username=username, password="testpass123")
    UserGroups.objects.create(user=user, authentik_id=f"{username}-uid", groups=groups)

    # Blue team users need a Team + DiscordLink with team assignment
    team = None
    if role == "blue_team":
        team, _ = Team.objects.get_or_create(
            team_number=1,
            defaults={
                "team_name": "Test Team 01",
                "authentik_group": "WCComps_BlueTeam01",
                "is_active": True,
            },
        )

    DiscordLink.objects.create(
        user=user,
        discord_id=9000000 + hash(role) % 1000000,
        discord_username=username,
        team=team,
        is_active=True,
    )

    return user


def create_session_context(
    pw_browser: Browser,
    live_server: "LiveServer",
    user: "User | None",
) -> BrowserContext:
    """Create a Playwright BrowserContext with the user's session cookie injected."""
    context = pw_browser.new_context(viewport={"width": 1920, "height": 1080})

    if user is not None:
        # force_login creates a real session in the test DB
        client = Client()
        client.force_login(user)
        session_cookie = client.cookies["sessionid"]
        context.add_cookies(
            [
                {
                    "name": "sessionid",
                    "value": session_cookie.value,
                    "url": live_server.url,
                }
            ]
        )

    return context


def visit_and_capture_errors(
    context: BrowserContext,
    url: str,
) -> tuple[Page, int, list[str]]:
    """Navigate to a URL, capture console errors and page errors.

    Returns (page, status_code, errors).
    """
    page = context.new_page()
    errors: list[str] = []

    page.on(
        "console",
        lambda msg: errors.append(f"[console.error] {msg.text}")
        if msg.type == "error"
        else None,
    )
    page.on("pageerror", lambda err: errors.append(f"[pageerror] {err}"))

    response = page.goto(url, wait_until="networkidle")
    status_code = response.status if response else 0

    return page, status_code, errors
