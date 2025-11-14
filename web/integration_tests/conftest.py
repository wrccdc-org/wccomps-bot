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


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker):
    """
    Set up test database with migrations.
    This runs once per test session.
    """
    from django.core.management import call_command

    with django_db_blocker.unblock():
        # Create database schema
        call_command("migrate", "--noinput", verbosity=0)


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
    from ticketing.models import Ticket
    from person.models import Person
    from django.contrib.auth import get_user_model

    User = get_user_model()

    try:
        # Delete in correct order (respecting foreign keys)
        # 1. Delete tickets first (they reference teams/persons)
        Ticket.objects.filter(title__startswith="[INTEGRATION TEST]").delete()

        # 2. Get test persons and their user IDs
        test_persons = Person.objects.filter(authentik_username__startswith="test_")
        test_user_ids = list(test_persons.values_list("user_id", flat=True))

        # 3. Delete persons (this won't cascade to users because User is parent)
        test_persons.delete()

        # 4. Delete users
        User.objects.filter(id__in=test_user_ids).delete()

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
    team, created = Team.objects.get_or_create(
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
def live_server_url(live_server):
    """Get live server URL for browser tests."""
    return live_server.url


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
    # Navigate to login URL
    page.goto(f"{live_server_url}/accounts/oidc/authentik/login/")

    # Fill in Authentik login form
    page.fill('input[name="uid_field"]', authentik_credentials["username"])
    page.fill('input[type="password"]', authentik_credentials["password"])
    page.click('button[type="submit"]')

    # Wait for redirect back to application
    page.wait_for_url(f"{live_server_url}/**", timeout=10000)

    return page


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
    from ticketing.models import Ticket
    from team.models import Team

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
    config.addinivalue_line(
        "markers", "critical: Critical tests that must pass on every deployment"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests with real database and APIs"
    )
    config.addinivalue_line(
        "markers", "browser: Browser-based UI tests using Playwright"
    )
    config.addinivalue_line(
        "markers", "load: Load and stress tests for concurrency and performance"
    )
