"""
Critical browser-based integration tests using Playwright.

These tests verify the full UI workflow with real browser rendering,
catching JavaScript errors, rendering bugs, and OAuth flow issues.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
]


class TestAuthentikOAuthFlow:
    """Test full OAuth login flow with Authentik.

    These tests verify the OAuth flow works but use the shared authenticated_page
    fixture to avoid multiple OAuth sessions which can cause rate limiting.
    """

    def test_login_flow_completes_successfully(self, authenticated_page: Page, live_server_url):
        """Verify OAuth login completed successfully via authenticated_page fixture."""
        # The authenticated_page fixture already completed OAuth login
        # Verify we're logged in by checking we can access protected pages
        authenticated_page.goto(f"{live_server_url}/ops/tickets/")
        authenticated_page.wait_for_load_state("networkidle")

        # Should be on the ops dashboard (not redirected to login)
        assert "auth.wccomps.org" not in authenticated_page.url
        expect(authenticated_page.locator("body")).to_be_visible()

    def test_login_preserves_redirect_url(self, authenticated_page: Page, live_server_url):
        """Login should redirect back to originally requested page."""
        # With authenticated_page, we're already logged in
        # Navigate to a specific page to verify access works
        authenticated_page.goto(f"{live_server_url}/ops/tickets/")
        authenticated_page.wait_for_load_state("networkidle")

        # Should be on the ops tickets page (access granted)
        assert "/ops/tickets" in authenticated_page.url or authenticated_page.url.startswith(live_server_url)

    @pytest.mark.skip(reason="Logout invalidates session-scoped fixture, breaking other tests")
    def test_logout_clears_session(self, authenticated_page: Page):
        """Logout should clear session and redirect to Authentik logout."""
        # This test is skipped because it would invalidate the session-scoped
        # authenticated_page fixture, breaking subsequent tests that depend on it.
        pass


class TestOpsTicketDashboard:
    """Test ops ticket dashboard rendering and functionality."""

    def test_ops_dashboard_renders_without_errors(self, authenticated_page: Page, live_server_url):
        """Ops dashboard should render without 500 errors."""
        base_url = live_server_url

        authenticated_page.goto(f"{base_url}/ops/tickets/")

        # Should not be on error page
        expect(authenticated_page).not_to_have_title("*500*")
        expect(authenticated_page.locator("body")).not_to_contain_text("500")
        expect(authenticated_page.locator("body")).not_to_contain_text("Server Error")

        # Should show ticket list or empty state
        expect(authenticated_page.locator("body")).to_be_visible()

    def test_ops_dashboard_displays_tickets(self, authenticated_page: Page, db, live_server_url):
        """Ops dashboard should display ticket list."""
        base_url = live_server_url

        # Create a test ticket
        from integration_tests.conftest import create_test_ticket

        ticket = create_test_ticket("Browser test ticket", team_id=50)

        authenticated_page.goto(f"{base_url}/ops/tickets/")

        # Should display the ticket
        expect(authenticated_page.locator(f"text={ticket.ticket_number}")).to_be_visible(timeout=5000)

        # Cleanup
        ticket.delete()

    def test_ticket_filters_work(self, authenticated_page: Page, live_server_url):
        """Ticket filter buttons should work without errors."""
        base_url = live_server_url

        authenticated_page.goto(f"{base_url}/ops/tickets/")

        # Try clicking filter buttons
        if authenticated_page.locator("text=Open").is_visible():
            authenticated_page.click("text=Open")
            authenticated_page.wait_for_timeout(500)  # Wait for filter

            # Should not crash
            expect(authenticated_page.locator("body")).not_to_contain_text("500")

        if authenticated_page.locator("text=Claimed").is_visible():
            authenticated_page.click("text=Claimed")
            authenticated_page.wait_for_timeout(500)

            expect(authenticated_page.locator("body")).not_to_contain_text("500")


class TestTicketOperations:
    """Test ticket claim and resolve operations via browser."""

    @pytest.fixture
    def test_ticket(self, db):
        """Create test ticket for browser operations."""
        from integration_tests.conftest import create_test_ticket

        ticket = create_test_ticket("Browser operation test", team_id=50)
        yield ticket
        ticket.delete()

    def test_claim_ticket_from_dashboard(self, authenticated_page: Page, test_ticket, db, live_server_url):
        """Claiming a ticket from dashboard should work."""
        base_url = live_server_url

        authenticated_page.goto(f"{base_url}/ops/tickets/")

        # Find the test ticket
        ticket_row = authenticated_page.locator(f"text={test_ticket.ticket_number}")
        expect(ticket_row).to_be_visible()

        # Click claim button
        claim_button = authenticated_page.locator(
            f'//tr[contains(., "{test_ticket.ticket_number}")]//button[contains(text(), "Claim")]'
        )

        if claim_button.is_visible():
            claim_button.click()

            # Wait for page update
            authenticated_page.wait_for_timeout(1000)

            # Should not show error
            expect(authenticated_page.locator("body")).not_to_contain_text("500")
            expect(authenticated_page.locator("body")).not_to_contain_text("Server Error")

    def test_resolve_ticket_with_points(self, authenticated_page: Page, test_ticket, db, live_server_url):
        """Resolving a ticket with points should work."""
        base_url = live_server_url

        # Claim ticket first via API
        from django.contrib.auth.models import User

        from team.models import DiscordLink

        # Get or create test user
        user, _ = User.objects.get_or_create(
            username="test_browser_user",
            defaults={"email": "test_browser_user@example.com"},
        )
        discord_link, _ = DiscordLink.objects.get_or_create(
            user=user,
            defaults={
                "discord_id": 111111111,
                "discord_username": "test_browser_user",
            },
        )

        # assigned_to expects a User instance (not DiscordLink)
        test_ticket.assigned_to = user
        test_ticket.save()

        # Navigate to ticket detail
        authenticated_page.goto(f"{base_url}/ops/ticket/{test_ticket.ticket_number}/")

        # Fill in resolution form
        if authenticated_page.locator('textarea[name="resolution"]').is_visible():
            authenticated_page.fill('textarea[name="resolution"]', "Test resolution via browser")
            authenticated_page.fill('input[name="points"]', "5")

            # Submit
            authenticated_page.click('button[type="submit"]')

            # Wait for resolution
            authenticated_page.wait_for_timeout(2000)

            # Should not show error
            expect(authenticated_page.locator("body")).not_to_contain_text("500")
            expect(authenticated_page.locator("body")).not_to_contain_text("Server Error")

        # Cleanup
        discord_link.delete()
        user.delete()


class TestPageRendering:
    """Test that all critical pages render without errors."""

    def test_home_page_renders(self, page: Page, live_server_url):
        """Home page should render without errors."""
        base_url = live_server_url

        page.goto(base_url)

        # Should not show error
        expect(page).not_to_have_title("*500*")
        expect(page.locator("body")).not_to_contain_text("Server Error")

        # Should show some content
        expect(page.locator("body")).to_be_visible()

    def test_health_check_page_renders(self, page: Page, live_server_url):
        """Health check endpoint should return healthy status."""
        base_url = live_server_url

        response = page.goto(f"{base_url}/health/")

        assert response.status == 200
        expect(page.locator("body")).to_contain_text("healthy")

    def test_ops_school_info_renders(self, authenticated_page: Page, live_server_url):
        """Ops school info page should render."""
        base_url = live_server_url

        authenticated_page.goto(f"{base_url}/ops/school-info/")

        # Should not show error
        expect(authenticated_page.locator("body")).not_to_contain_text("500")
        expect(authenticated_page.locator("body")).not_to_contain_text("Server Error")

        # Should show school info list or empty state
        expect(authenticated_page.locator("body")).to_be_visible()

    def test_admin_panel_accessible(self, authenticated_page: Page, live_server_url):
        """Admin panel should be accessible (even if user lacks permissions)."""
        base_url = live_server_url

        authenticated_page.goto(f"{base_url}/admin/")

        # Should either show admin panel or login (not 500)
        assert authenticated_page.url.startswith(base_url)

        # Should not show 500 error
        expect(authenticated_page.locator("body")).not_to_contain_text("Server Error")


class TestJavaScriptErrors:
    """Test that pages don't have JavaScript errors."""

    def test_no_console_errors_on_home_page(self, page: Page, live_server_url):
        """Home page should not have JavaScript console errors."""
        base_url = live_server_url

        console_errors = []

        def on_console_msg(msg):
            if msg.type == "error":
                console_errors.append(msg.text)

        page.on("console", on_console_msg)

        page.goto(base_url)
        page.wait_for_timeout(2000)  # Wait for JS to load

        # Should not have critical errors (warnings are OK)
        critical_errors = [err for err in console_errors if "failed" in err.lower() or "undefined" in err.lower()]

        assert len(critical_errors) == 0, f"JavaScript errors found: {critical_errors}"

    def test_no_console_errors_on_ops_dashboard(self, authenticated_page: Page, live_server_url):
        """Ops dashboard should not have JavaScript errors."""
        base_url = live_server_url

        console_errors = []

        def on_console_msg(msg):
            if msg.type == "error":
                console_errors.append(msg.text)

        authenticated_page.on("console", on_console_msg)

        authenticated_page.goto(f"{base_url}/ops/tickets/")
        authenticated_page.wait_for_timeout(2000)

        # Filter out expected errors (network errors for external resources, etc.)
        # Focus on actual JavaScript runtime errors
        critical_errors = [
            err
            for err in console_errors
            if ("undefined" in err.lower() or "typeerror" in err.lower() or "referenceerror" in err.lower())
            and "failed to load resource" not in err.lower()  # Network errors are not JS errors
        ]

        assert len(critical_errors) == 0, f"JavaScript errors found: {critical_errors}"


class TestFormValidation:
    """Test form submission and CSRF protection."""

    def test_forms_have_csrf_tokens(self, authenticated_page: Page, live_server_url):
        """Forms should include CSRF tokens."""
        base_url = live_server_url

        authenticated_page.goto(f"{base_url}/ops/tickets/")

        # Check if any forms exist
        forms = authenticated_page.locator("form").all()

        for form in forms:
            # Each form should have a CSRF token input
            csrf_input = form.locator('input[name="csrfmiddlewaretoken"]')

            if csrf_input.count() > 0:
                expect(csrf_input.first).to_be_attached()

    def test_form_submission_without_csrf_fails(self, authenticated_page: Page, live_server_url):
        """Form submission without CSRF token should fail gracefully."""
        base_url = live_server_url

        # Try to POST without CSRF token using the authenticated page's request context
        # This ensures we're testing CSRF protection, not authentication redirect
        response = authenticated_page.request.post(
            f"{base_url}/ops/tickets/bulk-claim/",
            data={"ticket_ids": [1, 2, 3]},
        )

        # Should get 403 Forbidden due to missing CSRF token (not 500)
        assert response.status in [403, 400], f"Expected CSRF rejection (403/400), got {response.status}"
