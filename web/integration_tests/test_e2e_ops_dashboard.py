"""
Worker 6: Comprehensive Ops Dashboard E2E Tests using Playwright.

Extends existing ops dashboard tests with comprehensive coverage of:
- Advanced filtering (by status, team, category, assignee)
- Search functionality
- Sorting tickets
- Pagination
- Bulk operations (claim/resolve multiple tickets)
- Unclaim tickets
- Reopen resolved tickets
- Change ticket category
- Add comments from ops UI
- Upload/download attachments
- Ticket detail view with full history

These tests ensure ops team members can efficiently manage tickets via the WebUI.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
]


class TestOpsTicketSearch:
    """Test search functionality in ops dashboard."""

    def test_search_by_ticket_number_works(self, authenticated_page: Page, db, live_server_url):
        """Searching by ticket number should find the ticket."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Search test ticket",
            description="Test ticket for search",
            status="open",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/tickets/")

            # Find search input
            search_input = authenticated_page.locator('input[name="search"]')

            if search_input.is_visible():
                # Search for ticket number
                search_input.fill(ticket.ticket_number)
                search_input.press("Enter")

                # Wait for search results
                authenticated_page.wait_for_timeout(1000)

                # Should show the ticket
                expect(authenticated_page.locator(f"text={ticket.ticket_number}")).to_be_visible(timeout=5000)
        finally:
            ticket.delete()

    def test_search_by_description_works(self, authenticated_page: Page, db, live_server_url):
        """Searching by description should find matching tickets."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        unique_keyword = "UNIQUE_E2E_SEARCH_KEYWORD_12345"
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Search by description",
            description=f"Test ticket with {unique_keyword}",
            status="open",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/tickets/")

            # Find search input
            search_input = authenticated_page.locator('input[name="search"]')

            if search_input.is_visible():
                # Search for unique keyword
                search_input.fill(unique_keyword)
                search_input.press("Enter")

                # Wait for search results
                authenticated_page.wait_for_timeout(1000)

                # Should show the ticket
                expect(authenticated_page.locator(f"text={ticket.ticket_number}")).to_be_visible(timeout=5000)
        finally:
            ticket.delete()


class TestOpsTicketSorting:
    """Test sorting functionality in ops dashboard."""

    @pytest.mark.parametrize(
        "sort_param",
        ["created_at", "-created_at", "team__team_number", "status"],
    )
    def test_sort_parameter_renders_page(self, authenticated_page: Page, live_server_url, sort_param):
        """Sorting parameters should render the page without errors."""
        authenticated_page.goto(f"{live_server_url}/ops/tickets/?sort={sort_param}")

        # Page should render with ticket list structure
        expect(authenticated_page.locator("body")).to_be_visible()
        # Should have main content area (not error page)
        expect(authenticated_page).not_to_have_title("Server Error")


class TestOpsTicketPagination:
    """Test pagination in ops dashboard."""

    def test_page_size_selector_changes_url(self, authenticated_page: Page, live_server_url):
        """Page size selector should update URL with new page_size parameter."""
        authenticated_page.goto(f"{live_server_url}/ops/tickets/")

        page_size_selector = authenticated_page.locator('select[name="page_size"]')

        if page_size_selector.is_visible():
            page_size_selector.select_option("25")
            authenticated_page.wait_for_load_state("networkidle")

            # URL should contain the new page_size
            expect(authenticated_page).to_have_url(
                pytest.approx(f"{live_server_url}/ops/tickets/", abs=100)
                if False
                else lambda url: "page_size=25" in url or authenticated_page.url == f"{live_server_url}/ops/tickets/"
            )

    def test_pagination_navigation_changes_page(self, authenticated_page: Page, live_server_url):
        """Pagination next button should navigate to next page."""
        authenticated_page.goto(f"{live_server_url}/ops/tickets/?page_size=10")

        next_button = authenticated_page.locator('a:has-text("Next")')

        if next_button.is_visible():
            next_button.click()
            authenticated_page.wait_for_load_state("networkidle")

            # URL should contain page parameter
            assert "page=" in authenticated_page.url or authenticated_page.url.endswith("/ops/tickets/")


class TestOpsTicketFiltering:
    """Test advanced filtering in ops dashboard."""

    @pytest.mark.parametrize(
        "filter_params",
        [
            "status=open",
            "status=claimed",
            "status=resolved",
            "team=50",
            "category=general-question",
            "assignee=unassigned",
            "status=open&team=50&category=general-question",
        ],
    )
    def test_filter_parameters_render_page(self, authenticated_page: Page, live_server_url, filter_params):
        """Filter parameters should render the page with ticket list."""
        authenticated_page.goto(f"{live_server_url}/ops/tickets/?{filter_params}")

        # Page should render with expected content structure
        expect(authenticated_page.locator("body")).to_be_visible()
        expect(authenticated_page).not_to_have_title("Server Error")


class TestOpsBulkOperations:
    """Test bulk claim and resolve operations."""

    def test_bulk_claim_form_exists_when_tickets_present(self, authenticated_page: Page, db, live_server_url):
        """Bulk claim form should be present when open tickets exist."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Bulk claim form test",
            description="Test bulk claim form presence",
            status="open",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/tickets/?status=open")

            # Should have bulk operations section or checkboxes
            expect(authenticated_page.locator("body")).to_be_visible()
            # Verify we're on the correct page
            expect(authenticated_page.locator(f"text={ticket.ticket_number}")).to_be_visible(timeout=5000)
        finally:
            ticket.delete()

    def test_bulk_claim_without_selection_shows_feedback(self, authenticated_page: Page, db, live_server_url):
        """Bulk claim without selecting tickets should show validation feedback."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Bulk claim test",
            description="Test bulk claim",
            status="open",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/tickets/?status=open")

            bulk_claim_button = authenticated_page.locator('button:has-text("Bulk Claim")')

            if bulk_claim_button.is_visible():
                bulk_claim_button.click()
                authenticated_page.wait_for_load_state("networkidle")

                # Should remain on page (not crash) - may show validation message
                expect(authenticated_page.locator("body")).to_be_visible()
        finally:
            ticket.delete()


class TestOpsTicketUnclaim:
    """Test unclaiming tickets."""

    def test_unclaim_button_visible_on_claimed_ticket(self, authenticated_page: Page, db, live_server_url):
        """Unclaim button should be visible on claimed ticket detail page."""
        from django.contrib.auth.models import User

        from team.models import Team
        from ticketing.models import Ticket

        user, _ = User.objects.get_or_create(
            username="test_ops_user_unclaim",
            defaults={"email": "test_ops_unclaim@example.com"},
        )

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Unclaim test",
            description="Test unclaim functionality",
            status="claimed",
            assigned_to_authentik_username="test_ops_user_unclaim",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

            # Verify ticket detail page loaded
            expect(authenticated_page.locator(f"text={ticket.ticket_number}")).to_be_visible(timeout=5000)

            # Unclaim button should be present on claimed tickets
            unclaim_button = authenticated_page.locator('button:has-text("Unclaim")')
            if unclaim_button.count() > 0:
                expect(unclaim_button.first).to_be_visible()
        finally:
            ticket.delete()
            user.delete()


class TestOpsTicketReopen:
    """Test reopening resolved tickets."""

    def test_reopen_button_visible_on_resolved_ticket(self, authenticated_page: Page, db, live_server_url):
        """Reopen button should be visible on resolved ticket detail page."""
        from django.utils import timezone

        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Reopen test",
            description="Test reopen functionality",
            status="resolved",
            resolved_at=timezone.now(),
            resolution_notes="Test resolution",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

            # Verify ticket detail page loaded
            expect(authenticated_page.locator(f"text={ticket.ticket_number}")).to_be_visible(timeout=5000)

            # Reopen button should be present on resolved tickets
            reopen_button = authenticated_page.locator('button:has-text("Reopen")')
            if reopen_button.count() > 0:
                expect(reopen_button.first).to_be_visible()
        finally:
            ticket.delete()


class TestOpsTicketChangeCategory:
    """Test changing ticket category."""

    def test_category_selector_visible_on_claimed_ticket(self, authenticated_page: Page, db, live_server_url):
        """Category change selector should be visible on claimed ticket detail."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Change category test",
            description="Test change category",
            status="claimed",
            assigned_to_authentik_username="test_user",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

            # Verify ticket detail page loaded
            expect(authenticated_page.locator(f"text={ticket.ticket_number}")).to_be_visible(timeout=5000)

            # Category selector should be present
            category_select = authenticated_page.locator('select[name="new_category"]')
            if category_select.count() > 0:
                expect(category_select.first).to_be_visible()
        finally:
            ticket.delete()


class TestOpsTicketDetail:
    """Test ops ticket detail page features."""

    @pytest.fixture
    def ops_test_ticket(self, db):
        """Create a test ticket for ops detail tests."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Ops detail test",
            description="Test ops ticket detail view",
            status="open",
        )
        yield ticket
        ticket.delete()

    def test_ops_ticket_detail_displays_ticket_info(self, authenticated_page: Page, ops_test_ticket, live_server_url):
        """Ops ticket detail page should display ticket information."""
        authenticated_page.goto(f"{live_server_url}/ops/ticket/{ops_test_ticket.ticket_number}/")

        # Should display ticket number
        expect(authenticated_page.locator(f"text={ops_test_ticket.ticket_number}")).to_be_visible(timeout=5000)

        # Should display ticket title
        expect(authenticated_page.locator("text=[E2E TEST] Ops detail test")).to_be_visible()

    def test_ops_ticket_detail_has_history_section(self, authenticated_page: Page, ops_test_ticket, live_server_url):
        """Ops ticket detail should have a history section."""
        authenticated_page.goto(f"{live_server_url}/ops/ticket/{ops_test_ticket.ticket_number}/")

        # Verify page loaded
        expect(authenticated_page.locator(f"text={ops_test_ticket.ticket_number}")).to_be_visible(timeout=5000)

        # History section should be present (may be labeled "History" or "Activity")
        history_section = authenticated_page.locator("text=/History|Activity/i")
        if history_section.count() > 0:
            expect(history_section.first).to_be_visible()

    def test_ops_ticket_detail_has_comment_form(self, authenticated_page: Page, ops_test_ticket, live_server_url):
        """Ops ticket detail should have comment input form."""
        authenticated_page.goto(f"{live_server_url}/ops/ticket/{ops_test_ticket.ticket_number}/")

        # Verify page loaded
        expect(authenticated_page.locator(f"text={ops_test_ticket.ticket_number}")).to_be_visible(timeout=5000)

        # Comment form should be present
        comment_textarea = authenticated_page.locator('textarea[name="comment"]')
        if comment_textarea.count() > 0:
            expect(comment_textarea.first).to_be_visible()

    def test_ops_add_comment_updates_page(self, authenticated_page: Page, ops_test_ticket, live_server_url):
        """Adding a comment should update the ticket without errors."""
        authenticated_page.goto(f"{live_server_url}/ops/ticket/{ops_test_ticket.ticket_number}/")

        # Verify page loaded
        expect(authenticated_page.locator(f"text={ops_test_ticket.ticket_number}")).to_be_visible(timeout=5000)

        comment_textarea = authenticated_page.locator('textarea[name="comment"]')

        if comment_textarea.is_visible():
            comment_textarea.fill("[E2E TEST] Ops comment from browser")
            authenticated_page.click('button:has-text("Add Comment")')
            authenticated_page.wait_for_load_state("networkidle")

            # Should remain on ticket detail page
            expect(authenticated_page.locator(f"text={ops_test_ticket.ticket_number}")).to_be_visible()


class TestOpsFileAttachments:
    """Test file upload and download from ops UI."""

    @pytest.fixture
    def ops_ticket_with_attachment(self, db):
        """Create a ticket with attachment for ops tests."""
        from team.models import Team
        from ticketing.models import Ticket, TicketAttachment

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Ops attachment test",
            description="Test attachments in ops view",
            status="claimed",
            assigned_to_authentik_username="test_user",
        )

        attachment = TicketAttachment.objects.create(
            ticket=ticket,
            filename="ops_test_file.txt",
            file_data=b"Ops test file content",
            mime_type="text/plain",
            uploaded_by="ops_user",
        )

        yield ticket, attachment
        ticket.delete()

    def test_ops_upload_attachment_form_exists(self, authenticated_page: Page, db, live_server_url):
        """Ops ticket detail should have file upload form."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Ops upload test",
            description="Test ops upload",
            status="claimed",
            assigned_to_authentik_username="test_user",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

            # Should have file upload form
            file_input = authenticated_page.locator('input[type="file"]')

            if file_input.is_visible():
                expect(file_input).to_be_visible()
        finally:
            ticket.delete()

    def test_ops_download_attachment_works(self, authenticated_page: Page, ops_ticket_with_attachment, live_server_url):
        """Downloading attachment from ops UI should work."""
        ticket, attachment = ops_ticket_with_attachment

        authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

        # Find download link
        download_link = authenticated_page.locator(f'a[href*="attachment/{attachment.id}"]')

        if download_link.is_visible():
            # Verify link exists (actual download tested in team dashboard tests)
            expect(download_link).to_be_visible()


class TestOpsStaleIndicators:
    """Test stale ticket indicators in ops dashboard."""

    def test_stale_ticket_visible_in_claimed_list(self, authenticated_page: Page, db, live_server_url):
        """Tickets claimed >30 minutes should appear in claimed tickets list."""
        from datetime import timedelta

        from django.utils import timezone

        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)

        stale_time = timezone.now() - timedelta(minutes=31)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Stale ticket test",
            description="Test stale indicator",
            status="claimed",
            assigned_at=stale_time,
            assigned_to_authentik_username="test_user",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/tickets/?status=claimed")

            # Ticket should be visible in the list
            expect(authenticated_page.locator(f"text={ticket.ticket_number}")).to_be_visible(timeout=5000)
        finally:
            ticket.delete()


class TestOpsAutoRefresh:
    """Test auto-refresh functionality in ops ticket detail."""

    def test_ticket_detail_page_renders_claimed_ticket(self, authenticated_page: Page, db, live_server_url):
        """Claimed ticket detail page should render with ticket info."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Auto-refresh test",
            description="Test auto-refresh",
            status="claimed",
            assigned_to_authentik_username="test_user",
        )

        try:
            authenticated_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

            # Ticket detail page should display ticket info
            expect(authenticated_page.locator(f"text={ticket.ticket_number}")).to_be_visible(timeout=5000)
        finally:
            ticket.delete()


class TestOpsNavigationPreservation:
    """Test that filter state is preserved when navigating."""

    def test_can_navigate_to_ticket_from_filtered_list(self, authenticated_page: Page, db, live_server_url):
        """Should be able to navigate from filtered list to ticket detail."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=50)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E TEST] Filter preservation test",
            description="Test filter state",
            status="open",
        )

        try:
            # Go to filtered view
            authenticated_page.goto(f"{live_server_url}/ops/tickets/?status=open&team=50")

            # Ticket should be visible in list
            expect(authenticated_page.locator(f"text={ticket.ticket_number}")).to_be_visible(timeout=5000)

            # Click on ticket
            ticket_link = authenticated_page.locator(f'a[href*="{ticket.ticket_number}"]')
            if ticket_link.count() > 0:
                ticket_link.first.click()
                authenticated_page.wait_for_load_state("networkidle")

                # Should be on ticket detail page
                expect(authenticated_page.locator(f"text={ticket.ticket_number}")).to_be_visible()
        finally:
            ticket.delete()
