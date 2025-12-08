"""
Integration test configuration and fixtures.

These tests use real PostgreSQL, real Authentik API, and real Discord API
to catch integration issues before deployment.
"""

import os
from pathlib import Path

import django
import pytest
from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright

# IMPORTANT: Set environment variables BEFORE calling django.setup()
# Load test environment variables first
env_test_path = Path(__file__).parent.parent.parent / ".env.test"
if env_test_path.exists():
    load_dotenv(env_test_path)

# Allow sync database operations in async context detection.
# Required for pytest-asyncio + pytest-django + Playwright live_server compatibility.
# See: https://github.com/microsoft/playwright-pytest/issues/29
# This is safe in tests since we're not running concurrent database operations.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

# Override Django settings to use PostgreSQL for integration tests
# This MUST happen before django.setup() is called
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wccomps.settings")
os.environ["USE_POSTGRES_FOR_TESTS"] = "1"  # Disable SQLite override in settings.py
os.environ["DB_HOST"] = os.getenv("TEST_DB_HOST", "localhost")
os.environ["DB_PORT"] = os.getenv("TEST_DB_PORT", "5433")
os.environ["DB_NAME"] = os.getenv("TEST_DB_NAME", "wccomps_test")
os.environ["DB_USER"] = os.getenv("TEST_DB_USER", "test_user")
os.environ["DB_PASSWORD"] = os.getenv("TEST_DB_PASSWORD", "test_password")

# Check for .env.test
if not env_test_path.exists():
    pytest.skip(
        "No .env.test file found. Copy .env.test.example and fill in credentials.",
        allow_module_level=True,
    )

# Configure Django
django.setup()


# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture
def cleanup_test_data():
    """
    Manual cleanup fixture for tests that use transactional_db.

    Tests using db fixture get automatic rollback, but concurrent tests
    that need transactional_db must manually clean up.

    Usage:
        def test_something(transactional_db, cleanup_test_data):
            # Test code that commits to database
            pass
            # Cleanup runs after test
    """
    # Run test
    yield

    # Clean up test data after test
    from django.contrib.auth import get_user_model

    from ticketing.models import Ticket

    user_model = get_user_model()

    try:
        # Delete in correct order (respecting foreign keys)
        # 1. Delete tickets first (they reference teams/discordlinks)
        Ticket.objects.filter(title__startswith="[INTEGRATION TEST]").delete()

        # 2. Get test users and delete them
        test_users = user_model.objects.filter(username__startswith="test_")
        test_users.delete()

    except Exception as e:
        # Log cleanup errors but don't fail tests
        import sys

        print(f"Warning: Cleanup error: {e}", file=sys.stderr)


# ============================================================================
# Authentication Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def authentik_credentials():
    """Get Authentik test user credentials from environment."""
    return {
        "username": os.getenv("TEST_AUTHENTIK_USERNAME"),
        "password": os.getenv("TEST_AUTHENTIK_PASSWORD"),
        "api_token": os.getenv("TEST_AUTHENTIK_API_TOKEN"),
    }


@pytest.fixture(scope="session")
def discord_credentials():
    """Get Discord test user credentials from environment."""
    return {
        "user_token": os.getenv("TEST_DISCORD_USER_TOKEN"),
        "username": os.getenv("TEST_DISCORD_USERNAME"),
    }


@pytest.fixture
def test_team_id(db):
    """Get test team ID (team 50) and ensure it exists."""
    from team.models import Team

    team_number = int(os.getenv("TEST_TEAM_ID", "50"))

    # Create team 50 if it doesn't exist
    _team, _created = Team.objects.get_or_create(
        team_number=team_number,
        defaults={
            "team_name": "Test Team 50",
            "authentik_group": "WCComps_BlueTeam50",
            "is_active": True,
        },
    )

    return team_number


@pytest.fixture
def authentik_client(authentik_credentials):
    """
    Create Authentik API client for real API calls.
    Uses real Authentik instance, not mocked.
    """
    from authentik_client import AuthenticatedClient

    api_token = authentik_credentials["api_token"]
    authentik_url = os.getenv("AUTHENTIK_URL", "https://auth.wccomps.org")

    return AuthenticatedClient(
        base_url=f"{authentik_url}/api/v3",
        token=api_token,
    )


# ============================================================================
# Browser (Playwright) Fixtures
# ============================================================================


@pytest.fixture(scope="session")
def live_server_url():
    """
    Get base URL for browser tests.

    For OAuth tests, use TEST_BASE_URL (a running server with OAuth callback registered).
    This is required because Django's live_server uses dynamic ports that can't be
    pre-registered with Authentik.
    """
    base_url = os.getenv("TEST_BASE_URL", "http://localhost:8000")
    return base_url.rstrip("/")


@pytest.fixture(scope="session")
def browser_context_args():
    """Configure browser context (headless, viewport, etc.)."""
    return {
        "viewport": {"width": 1920, "height": 1080},
        "ignore_https_errors": True,  # Allow self-signed certs in test env
    }


@pytest.fixture(scope="session")
def playwright_instance():
    """Create Playwright instance for the test session."""
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session")
def browser(playwright_instance):
    """Launch browser instance (headless Chromium)."""
    browser = playwright_instance.chromium.launch(headless=True)
    yield browser
    browser.close()


@pytest.fixture
def browser_context(browser, browser_context_args):
    """Create a new browser context for each test."""
    context = browser.new_context(**browser_context_args)
    yield context
    context.close()


@pytest.fixture
def page(browser_context) -> Page:
    """Create a new page for each test."""
    page = browser_context.new_page()
    yield page
    page.close()


@pytest.fixture
def authenticated_page(page, authentik_credentials, live_server_url) -> Page:
    """
    Create an authenticated page by logging in via Authentik OAuth.
    This performs a real OAuth login flow.
    """
    # Navigate to login URL (redirects to Authentik)
    page.goto(f"{live_server_url}/auth/login/")

    # Fill in Authentik login form (uidField is the actual field name)
    page.fill('input[name="uidField"]', authentik_credentials["username"])
    page.fill('input[name="password"]', authentik_credentials["password"])
    page.click('button[type="submit"]')

    # Handle MFA if present (requires TEST_TOTP_SECRET in .env.test)
    import os

    totp_secret = os.getenv("TEST_TOTP_SECRET")
    if totp_secret:
        try:
            import pyotp

            page.wait_for_timeout(2000)

            # Check if we're on MFA selection page
            if "Select an authentication method" in page.content():
                page.click("text=TOTP Device")
                page.wait_for_timeout(1000)

            # Enter TOTP code
            totp = pyotp.TOTP(totp_secret)
            page.wait_for_selector('input[name="code"]', timeout=5000)
            page.fill('input[name="code"]', totp.now())
            page.click('button[type="submit"]')
        except (ImportError, TimeoutError):
            pass  # pyotp not installed or no MFA prompt

    # Wait for redirect back to application
    page.wait_for_url(f"{live_server_url}/**", timeout=10000)

    return page


# ============================================================================
# Multi-User Browser Fixtures
# ============================================================================


def _perform_authentik_login(page, username: str, password: str, live_server_url: str):
    """Helper to perform Authentik OAuth login."""
    page.goto(f"{live_server_url}/accounts/oidc/authentik/login/")

    page.fill('input[name="uidField"]', username)
    page.fill('input[type="password"]', password)
    page.click('button[type="submit"]')

    # Handle MFA if present
    totp_secret = os.getenv("TEST_TOTP_SECRET")
    if totp_secret:
        try:
            import pyotp

            page.wait_for_timeout(2000)

            if "Select an authentication method" in page.content():
                page.click("text=TOTP Device")
                page.wait_for_timeout(1000)

            totp = pyotp.TOTP(totp_secret)
            page.wait_for_selector('input[name="code"]', timeout=5000)
            page.fill('input[name="code"]', totp.now())
            page.click('button[type="submit"]')
        except (ImportError, TimeoutError):
            pass

    page.wait_for_url(f"{live_server_url}/**", timeout=10000)
    return page


@pytest.fixture
def ops_user_credentials():
    """Ops/support user credentials from environment."""
    return {
        "username": os.getenv("TEST_OPS_USERNAME", os.getenv("TEST_AUTHENTIK_USERNAME")),
        "password": os.getenv("TEST_OPS_PASSWORD", os.getenv("TEST_AUTHENTIK_PASSWORD")),
    }


@pytest.fixture
def team_user_credentials():
    """Team member credentials from environment."""
    return {
        "username": os.getenv("TEST_TEAM_USERNAME", os.getenv("TEST_AUTHENTIK_USERNAME")),
        "password": os.getenv("TEST_TEAM_PASSWORD", os.getenv("TEST_AUTHENTIK_PASSWORD")),
    }


@pytest.fixture
def admin_user_credentials():
    """Admin user credentials from environment."""
    return {
        "username": os.getenv("TEST_ADMIN_USERNAME", os.getenv("TEST_AUTHENTIK_USERNAME")),
        "password": os.getenv("TEST_ADMIN_PASSWORD", os.getenv("TEST_AUTHENTIK_PASSWORD")),
    }


@pytest.fixture
def ops_page(browser, browser_context_args, ops_user_credentials, live_server_url) -> Page:
    """Browser page authenticated as ops/support user."""
    context = browser.new_context(**browser_context_args)
    page = context.new_page()
    _perform_authentik_login(page, ops_user_credentials["username"], ops_user_credentials["password"], live_server_url)
    yield page
    page.close()
    context.close()


def _ensure_team_membership(username: str, team_number: int) -> None:
    """Ensure user has team membership in the shared database."""
    from django.contrib.auth import get_user_model

    from team.models import DiscordLink, Team

    user_model = get_user_model()

    user = user_model.objects.filter(username=username).first()
    if not user:
        return

    team, _ = Team.objects.get_or_create(
        team_number=team_number,
        defaults={
            "team_name": f"Test Team {team_number}",
            "authentik_group": f"WCComps_BlueTeam{team_number}",
            "is_active": True,
        },
    )

    # Create or update DiscordLink
    link, created = DiscordLink.objects.get_or_create(
        user=user,
        defaults={
            "discord_id": 123456789012345678,  # Fake Discord ID for testing
            "team": team,
            "is_active": True,
        },
    )
    if not created and link.team != team:
        link.team = team
        link.is_active = True
        link.save()


@pytest.fixture
def team_page(browser, browser_context_args, team_user_credentials, live_server_url, transactional_db) -> Page:
    """Browser page authenticated as team member with team membership."""
    context = browser.new_context(**browser_context_args)
    page = context.new_page()
    _perform_authentik_login(
        page, team_user_credentials["username"], team_user_credentials["password"], live_server_url
    )

    # After OAuth login, ensure user has team membership
    # Uses transactional_db so changes are visible to the external server
    team_number = int(os.getenv("TEST_TEAM_ID", "50"))
    _ensure_team_membership(team_user_credentials["username"], team_number)

    # Refresh the page to pick up the new permissions
    page.reload()

    yield page
    page.close()
    context.close()


@pytest.fixture
def admin_page(browser, browser_context_args, admin_user_credentials, live_server_url) -> Page:
    """Browser page authenticated as admin user."""
    context = browser.new_context(**browser_context_args)
    page = context.new_page()
    _perform_authentik_login(
        page, admin_user_credentials["username"], admin_user_credentials["password"], live_server_url
    )
    yield page
    page.close()
    context.close()


# ============================================================================
# HTTP Client Fixtures
# ============================================================================


@pytest.fixture
def http_client():
    """Create HTTP client for API testing."""
    import requests

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "WCComps Integration Tests",
        }
    )

    yield session
    session.close()


@pytest.fixture
def authenticated_http_client(http_client, authentik_credentials):
    """
    Create authenticated HTTP client by performing OAuth login.
    Returns a requests.Session with valid session cookies.
    """
    # OAuth flow is complex to implement via HTTP client
    # Browser-based tests (authenticated_page fixture) handle this properly
    # This fixture is a placeholder for now
    return http_client


# ============================================================================
# Helper Functions
# ============================================================================


def create_test_ticket(title: str, description: str = "Test ticket", team_id: int = 50):
    """
    Create a test ticket in the database.
    Tickets are automatically marked with [INTEGRATION TEST] prefix.
    """
    from team.models import Team
    from ticketing.models import Ticket

    team = Team.objects.get(team_number=team_id)

    return Ticket.objects.create(
        title=f"[INTEGRATION TEST] {title}",
        description=description,
        team=team,
        status="open",
    )


def cleanup_test_tickets():
    """Manually clean up all test tickets."""
    from ticketing.models import Ticket

    Ticket.objects.filter(title__startswith="[INTEGRATION TEST]").delete()


# ============================================================================
# Pytest Configuration
# ============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "critical: Critical tests that must pass on every deployment")
    config.addinivalue_line("markers", "integration: Integration tests with real database and APIs")
    config.addinivalue_line("markers", "browser: Browser-based UI tests using Playwright")
    config.addinivalue_line("markers", "load: Load and stress tests for concurrency and performance")
