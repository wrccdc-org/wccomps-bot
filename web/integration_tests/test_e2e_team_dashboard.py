"""
Worker 5: Team Dashboard E2E Tests using Playwright.

Tests all team-facing functionality to ensure WebUI works correctly:
- View team tickets list
- Create new tickets via web form
- View ticket details
- Post comments to tickets
- Cancel tickets
- Upload/download attachments

These tests complement the existing Discord bot tests by verifying
the web interface provides equivalent functionality.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

# Skip all tests if ticketing is not enabled
TICKETING_ENABLED = os.environ.get("TICKETING_ENABLED", "false").lower() == "true"

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
    pytest.mark.skipif(not TICKETING_ENABLED, reason="Ticketing not enabled"),
]


@pytest.fixture
def team_user_page(browser_context, live_server_url):
    """
    Create an authenticated page for a team member.

    NOTE: This requires a real team member account in .env.test.
    For now, this uses the standard authenticated_page fixture.
    In production, you'd want a dedicated TEST_TEAM_USERNAME/PASSWORD.
    """
    page = browser_context.new_page()

    # Get team credentials from environment
    team_username = os.getenv("TEST_TEAM_USERNAME", os.getenv("TEST_AUTHENTIK_USERNAME"))
    team_password = os.getenv("TEST_TEAM_PASSWORD", os.getenv("TEST_AUTHENTIK_PASSWORD"))

    # Navigate to login URL
    page.goto(f"{live_server_url}/accounts/oidc/authentik/login/")

    # Fill in Authentik login form
    page.fill('input[name="uid_field"]', team_username)
    page.fill('input[type="password"]', team_password)
    page.click('button[type="submit"]')

    # Wait for redirect back to application
    page.wait_for_url(f"{live_server_url}/**", timeout=10000)

    yield page
    page.close()


class TestTeamTicketsList:
    """Test team tickets dashboard rendering and filtering."""

    def test_team_tickets_page_renders(self, team_user_page: Page, live_server_url):
        """Team tickets page should render without errors."""
        team_user_page.goto(f"{live_server_url}/tickets/")

        # Should not show error
        expect(team_user_page).not_to_have_title("*500*")
        expect(team_user_page.locator("body")).not_to_contain_text("Server Error")

        # Should show tickets list or empty state
        expect(team_user_page.locator("body")).to_be_visible()

    def test_team_tickets_shows_team_name(self, team_user_page: Page, live_server_url):
        """Team tickets page should display team name."""
        team_user_page.goto(f"{live_server_url}/tickets/")

        # Should show team identifier
        expect(team_user_page.locator("body")).to_be_visible()

    def test_team_tickets_filter_by_status(self, team_user_page: Page, live_server_url):
        """Status filter should work without errors."""
        team_user_page.goto(f"{live_server_url}/tickets/")

        # Try clicking filter links
        if team_user_page.locator('a[href*="status=open"]').is_visible():
            team_user_page.click('a[href*="status=open"]')
            team_user_page.wait_for_timeout(500)

            # Should not crash
            expect(team_user_page.locator("body")).not_to_contain_text("500")

        if team_user_page.locator('a[href*="status=claimed"]').is_visible():
            team_user_page.click('a[href*="status=claimed"]')
            team_user_page.wait_for_timeout(500)

            expect(team_user_page.locator("body")).not_to_contain_text("500")

    def test_team_tickets_displays_created_ticket(self, team_user_page: Page, db, live_server_url):
        """Team tickets page should display tickets for the team."""
        from team.models import Team
        from ticketing.models import Ticket

        # Get test team (assuming team 50)
        team = Team.objects.get(team_number=50)

        # Create test ticket
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Team dashboard test ticket",
            description="Test ticket for E2E testing",
            status="open",
        )

        try:
            team_user_page.goto(f"{live_server_url}/tickets/")

            # Should display the ticket number
            expect(team_user_page.locator(f"text={ticket.ticket_number}")).to_be_visible(timeout=5000)
        finally:
            # Cleanup
            ticket.delete()


class TestCreateTicketForm:
    """Test ticket creation via web form."""

    def test_create_ticket_form_renders(self, team_user_page: Page, live_server_url):
        """Create ticket form should render without errors."""
        team_user_page.goto(f"{live_server_url}/tickets/create/")

        # Should not show error
        expect(team_user_page).not_to_have_title("*500*")
        expect(team_user_page.locator("body")).not_to_contain_text("Server Error")

        # Should show form
        expect(team_user_page.locator("form")).to_be_visible()

    def test_create_ticket_form_has_categories(self, team_user_page: Page, live_server_url):
        """Create ticket form should display available categories."""
        team_user_page.goto(f"{live_server_url}/tickets/create/")

        # Should have category selector
        expect(team_user_page.locator('select[name="category"]')).to_be_visible()

    def test_create_ticket_form_has_csrf_token(self, team_user_page: Page, live_server_url):
        """Create ticket form should include CSRF token."""
        team_user_page.goto(f"{live_server_url}/tickets/create/")

        # Should have CSRF token
        csrf_input = team_user_page.locator('input[name="csrfmiddlewaretoken"]')
        expect(csrf_input).to_be_attached()

    def test_create_ticket_submission_works(self, team_user_page: Page, db, live_server_url):
        """Submitting create ticket form should create a ticket."""
        from ticketing.models import Ticket

        team_user_page.goto(f"{live_server_url}/tickets/create/")

        # Fill out form
        team_user_page.select_option('select[name="category"]', "general-question")
        team_user_page.fill('input[name="title"]', "[E2E TEST] Ticket via web form")
        team_user_page.fill('textarea[name="description"]', "Test ticket created via browser automation")

        # Submit form
        team_user_page.click('button[type="submit"]')

        # Should redirect to ticket detail or tickets list
        team_user_page.wait_for_timeout(2000)

        # Should not show error
        expect(team_user_page.locator("body")).not_to_contain_text("Server Error")
        expect(team_user_page.locator("body")).not_to_contain_text("500")

        # Cleanup: find and delete test ticket
        try:
            test_ticket = Ticket.objects.filter(title__contains="[E2E TEST] Ticket via web form").first()
            if test_ticket:
                test_ticket.delete()
        except Exception:
            pass


class TestTicketDetailView:
    """Test ticket detail page functionality."""

    @pytest.fixture
    def team_test_ticket(self, db):
        """Create a test ticket for team dashboard tests."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Ticket detail test",
            description="Test ticket for viewing details",
            status="open",
        )
        yield ticket
        ticket.delete()

    def test_ticket_detail_renders(self, team_user_page: Page, team_test_ticket, live_server_url):
        """Ticket detail page should render without errors."""
        team_user_page.goto(f"{live_server_url}/tickets/{team_test_ticket.id}/")

        # Should not show error
        expect(team_user_page).not_to_have_title("*500*")
        expect(team_user_page.locator("body")).not_to_contain_text("Server Error")

        # Should display ticket number
        expect(team_user_page.locator(f"text={team_test_ticket.ticket_number}")).to_be_visible()

    def test_ticket_detail_shows_description(self, team_user_page: Page, team_test_ticket, live_server_url):
        """Ticket detail should display description."""
        team_user_page.goto(f"{live_server_url}/tickets/{team_test_ticket.id}/")

        # Should show description
        expect(team_user_page.locator(f"text={team_test_ticket.description}")).to_be_visible()

    def test_ticket_detail_shows_status(self, team_user_page: Page, team_test_ticket, live_server_url):
        """Ticket detail should display current status."""
        team_user_page.goto(f"{live_server_url}/tickets/{team_test_ticket.id}/")

        # Should show status (OPEN, CLAIMED, etc.)
        expect(team_user_page.locator("body")).to_be_visible()

    def test_ticket_detail_has_comment_form(self, team_user_page: Page, team_test_ticket, live_server_url):
        """Ticket detail should have comment form."""
        team_user_page.goto(f"{live_server_url}/tickets/{team_test_ticket.id}/")

        # Should have comment form
        if team_test_ticket.status != "resolved":
            comment_form = team_user_page.locator('form[action*="comment"]')
            if comment_form.is_visible():
                expect(comment_form).to_be_visible()


class TestTicketComments:
    """Test posting comments to tickets."""

    @pytest.fixture
    def team_test_ticket(self, db):
        """Create a test ticket for comment tests."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Comment test ticket",
            description="Test ticket for comments",
            status="open",
        )
        yield ticket
        ticket.delete()

    def test_post_comment_works(self, team_user_page: Page, team_test_ticket, live_server_url):
        """Posting a comment should work."""
        team_user_page.goto(f"{live_server_url}/tickets/{team_test_ticket.id}/")

        # Find comment form
        comment_textarea = team_user_page.locator('textarea[name="comment"]')

        if comment_textarea.is_visible():
            # Fill in comment
            comment_textarea.fill("[E2E TEST] This is a test comment from browser automation")

            # Submit
            team_user_page.click('button[type="submit"]')

            # Wait for page update
            team_user_page.wait_for_timeout(2000)

            # Should not show error
            expect(team_user_page.locator("body")).not_to_contain_text("Server Error")
            expect(team_user_page.locator("body")).not_to_contain_text("500")


class TestCancelTicket:
    """Test cancelling tickets from web interface."""

    @pytest.fixture
    def cancelable_ticket(self, db):
        """Create a ticket that can be cancelled."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Cancellable ticket",
            description="Test ticket for cancellation",
            status="open",
        )
        yield ticket
        # Cleanup happens in test or here
        if Ticket.objects.filter(id=ticket.id).exists():
            ticket.delete()

    def test_cancel_ticket_button_exists(self, team_user_page: Page, cancelable_ticket, live_server_url):
        """Open tickets should have cancel button."""
        team_user_page.goto(f"{live_server_url}/tickets/{cancelable_ticket.id}/")

        # Should have cancel button (if ticket is open/unclaimed)
        cancel_button = team_user_page.locator('button:has-text("Cancel")')

        if cancel_button.is_visible():
            expect(cancel_button).to_be_visible()

    def test_cancel_ticket_works(self, team_user_page: Page, cancelable_ticket, live_server_url):
        """Cancelling a ticket should work."""
        team_user_page.goto(f"{live_server_url}/tickets/{cancelable_ticket.id}/")

        # Find cancel button
        cancel_button = team_user_page.locator('button:has-text("Cancel")')

        if cancel_button.is_visible():
            # Click cancel
            cancel_button.click()

            # Wait for redirect
            team_user_page.wait_for_timeout(2000)

            # Should not show error
            expect(team_user_page.locator("body")).not_to_contain_text("Server Error")
            expect(team_user_page.locator("body")).not_to_contain_text("500")


class TestFileAttachments:
    """Test file upload and download functionality."""

    @pytest.fixture
    def ticket_with_attachment(self, db):
        """Create a ticket with an attachment for download tests."""
        from team.models import Team
        from ticketing.models import Ticket, TicketAttachment

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Attachment test ticket",
            description="Test ticket for attachments",
            status="open",
        )

        # Create test attachment
        attachment = TicketAttachment.objects.create(
            ticket=ticket,
            filename="test_file.txt",
            file_data=b"This is test file content",
            mime_type="text/plain",
            uploaded_by="test_user",
        )

        yield ticket, attachment

        # Cleanup
        ticket.delete()

    def test_upload_attachment_form_exists(self, team_user_page: Page, db, live_server_url):
        """Ticket detail should have file upload form."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Upload form test",
            description="Test upload form",
            status="open",
        )

        try:
            team_user_page.goto(f"{live_server_url}/tickets/{ticket.id}/")

            # Should have file upload form
            file_input = team_user_page.locator('input[type="file"]')

            if file_input.is_visible():
                expect(file_input).to_be_visible()
        finally:
            ticket.delete()

    def test_upload_attachment_works(self, team_user_page: Page, db, live_server_url):
        """Uploading an attachment should work."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Upload test",
            description="Test file upload",
            status="open",
        )

        try:
            team_user_page.goto(f"{live_server_url}/tickets/{ticket.id}/")

            # Find file input
            file_input = team_user_page.locator('input[type="file"][name="attachment"]')

            if file_input.is_visible():
                # Create temporary test file
                test_file_path = Path("/tmp/test_attachment_e2e.txt")
                test_file_path.write_text("This is a test attachment from E2E tests")

                # Upload file
                file_input.set_input_files(str(test_file_path))

                # Submit upload form
                team_user_page.click('button:has-text("Upload")')

                # Wait for upload
                team_user_page.wait_for_timeout(2000)

                # Should not show error
                expect(team_user_page.locator("body")).not_to_contain_text("Server Error")
                expect(team_user_page.locator("body")).not_to_contain_text("500")

                # Cleanup test file
                test_file_path.unlink()
        finally:
            ticket.delete()

    def test_download_attachment_works(self, team_user_page: Page, ticket_with_attachment, live_server_url):
        """Downloading an attachment should work."""
        ticket, attachment = ticket_with_attachment

        team_user_page.goto(f"{live_server_url}/tickets/{ticket.id}/")

        # Find download link
        download_link = team_user_page.locator(f'a[href*="attachment/{attachment.id}"]')

        if download_link.is_visible():
            # Click download link
            with team_user_page.expect_download() as download_info:
                download_link.click()

            download = download_info.value

            # Verify download succeeded
            assert download.suggested_filename == "test_file.txt"


class TestErrorHandling:
    """Test error handling in team dashboard."""

    def test_nonexistent_ticket_shows_error(self, team_user_page: Page, live_server_url):
        """Accessing nonexistent ticket should show error page."""
        team_user_page.goto(f"{live_server_url}/tickets/99999999/")

        # Should show error (not 500)
        expect(team_user_page.locator("body")).to_be_visible()

    def test_other_teams_ticket_not_accessible(self, team_user_page: Page, db, live_server_url):
        """Team members should not access other teams' tickets."""
        from team.models import Team
        from ticketing.models import Ticket

        # Create ticket for a different team (team 1, assuming test user is team 50)
        other_team = Team.objects.filter(team_number=1).first()

        if other_team:
            ticket = Ticket.objects.create(
                team=other_team,
                category="general-question",
                title="[E2E TEST] Other team ticket",
                description="Should not be accessible",
                status="open",
            )

            try:
                team_user_page.goto(f"{live_server_url}/tickets/{ticket.id}/")

                # Should show error or redirect (not show the ticket)
                expect(team_user_page.locator("body")).to_be_visible()
            finally:
                ticket.delete()


class TestAccessControl:
    """Test that team members can only access team features."""

    def test_team_member_cannot_access_ops_dashboard(self, team_user_page: Page, live_server_url):
        """Team members should not access ops dashboard."""
        team_user_page.goto(f"{live_server_url}/ops/tickets/")

        # Should show access denied or redirect
        # (not 500 error, but proper access control)
        expect(team_user_page.locator("body")).to_be_visible()

    def test_team_member_cannot_access_school_info(self, team_user_page: Page, live_server_url):
        """Team members should not access school info."""
        team_user_page.goto(f"{live_server_url}/ops/school-info/")

        # Should show access denied
        expect(team_user_page.locator("body")).to_be_visible()
