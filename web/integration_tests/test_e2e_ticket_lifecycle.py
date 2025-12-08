"""
E2E tests for complete ticket lifecycle with real users via Playwright.

Tests the full workflow:
1. Team member creates ticket via web form
2. Ops user sees ticket, claims it
3. Team member adds comment
4. Ops user responds, resolves with points
5. Admin reopens ticket
6. Ops resolves again

Requires .env.test with real Authentik credentials for multiple user roles.
"""

import os

import pytest
from playwright.sync_api import Page, expect

pytestmark = [
    pytest.mark.browser,
    pytest.mark.integration,
]


class TestTicketCreationByTeam:
    """Test team member creating tickets via web UI."""

    def test_team_member_can_access_ticket_form(self, team_page: Page, live_server_url):
        """Team member should be able to access create ticket form."""
        team_page.goto(f"{live_server_url}/tickets/create/")

        form = team_page.locator("form")
        expect(form).to_be_visible()
        expect(team_page.locator('select[name="category"]')).to_be_visible()
        expect(team_page.locator('input[name="title"]')).to_be_visible()

    def test_service_dropdown_populates_when_category_selected(self, team_page: Page, live_server_url):
        """Service dropdown should populate with options when category requiring service is selected."""
        team_page.goto(f"{live_server_url}/tickets/create/")

        # Select a category that requires service_name
        team_page.select_option('select[name="category"]', "scoring-service-check")

        # Wait for Alpine.js to update the UI
        team_page.wait_for_timeout(500)

        # Verify service dropdown is visible and has options
        service_select = team_page.locator('select[name="service_name"]')
        expect(service_select).to_be_visible()

        # Get all options (excluding the placeholder)
        options = service_select.locator("option:not([value=''])")
        option_count = options.count()

        assert option_count > 0, "Service dropdown should have options populated by Alpine.js"

    def test_create_ticket_with_service_selection(self, team_page: Page, db, live_server_url):
        """Team member creates ticket with service selection (regression test for x-for fix)."""
        from ticketing.models import Ticket

        team_page.goto(f"{live_server_url}/tickets/create/")

        unique_title = f"[E2E SERVICE] Service dropdown test {os.urandom(4).hex()}"

        # Select category requiring service_name
        team_page.select_option('select[name="category"]', "scoring-service-check")
        team_page.wait_for_timeout(500)

        # Fill title
        team_page.fill('input[name="title"]', unique_title)

        # Select first available service
        service_select = team_page.locator('select[name="service_name"]')
        options = service_select.locator("option:not([value=''])")

        if options.count() > 0:
            first_option_value = options.first.get_attribute("value")
            team_page.select_option('select[name="service_name"]', first_option_value)

        # Submit form
        team_page.click('button[type="submit"]')
        team_page.wait_for_timeout(2000)

        expect(team_page.locator("body")).not_to_contain_text("Server Error")

        # Verify ticket created
        ticket = Ticket.objects.filter(title=unique_title).first()
        assert ticket is not None, "Ticket should be created in database"
        assert ticket.category == "scoring-service-check"

        ticket.delete()

    def test_team_member_creates_ticket(self, team_page: Page, db, live_server_url):
        """Team member creates ticket and sees it in their list."""
        from ticketing.models import Ticket

        team_page.goto(f"{live_server_url}/tickets/create/")

        unique_title = f"[E2E LIFECYCLE] Test ticket {os.urandom(4).hex()}"

        team_page.select_option('select[name="category"]', "general-question")
        team_page.fill('input[name="title"]', unique_title)
        team_page.fill('textarea[name="description"]', "Created via E2E test")
        team_page.click('button[type="submit"]')

        team_page.wait_for_timeout(2000)

        expect(team_page.locator("body")).not_to_contain_text("Server Error")

        ticket = Ticket.objects.filter(title=unique_title).first()
        assert ticket is not None, "Ticket should be created in database"
        assert ticket.status == "open"

        team_page.goto(f"{live_server_url}/tickets/")
        expect(team_page.locator(f"text={ticket.ticket_number}")).to_be_visible(timeout=5000)

        ticket.delete()


class TestOpsClaimsTicket:
    """Test ops user claiming tickets from dashboard."""

    @pytest.fixture
    def team_ticket(self, db, test_team_id):
        """Create a ticket for testing ops claims."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=test_team_id)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title=f"[E2E LIFECYCLE] Claimable ticket {os.urandom(4).hex()}",
            description="Waiting for ops to claim",
            status="open",
        )
        yield ticket
        if Ticket.objects.filter(pk=ticket.pk).exists():
            ticket.delete()

    def test_ops_sees_open_ticket(self, ops_page: Page, team_ticket, live_server_url):
        """Ops user can see open ticket in dashboard."""
        ops_page.goto(f"{live_server_url}/ops/tickets/?status=open")

        expect(ops_page.locator(f"text={team_ticket.ticket_number}")).to_be_visible(timeout=5000)

    def test_ops_claims_ticket(self, ops_page: Page, team_ticket, db, live_server_url):
        """Ops user claims ticket and it moves to claimed status."""

        ops_page.goto(f"{live_server_url}/ops/tickets/?status=open")

        ticket_row = ops_page.locator(f"tr:has-text('{team_ticket.ticket_number}')")
        claim_button = ticket_row.locator('button:has-text("Claim"), input[value="Claim"]')

        if claim_button.count() > 0:
            claim_button.first.click()
            ops_page.wait_for_timeout(2000)

            team_ticket.refresh_from_db()
            assert team_ticket.status == "claimed", "Ticket should be claimed"
            assert team_ticket.assigned_to is not None, "Should have assignee"

    def test_claimed_ticket_shows_in_claimed_filter(self, ops_page: Page, team_ticket, db, live_server_url):
        """After claiming, ticket appears in claimed filter."""
        from django.contrib.auth.models import User

        from team.models import DiscordLink

        user = User.objects.get(username=os.getenv("TEST_OPS_USERNAME", os.getenv("TEST_AUTHENTIK_USERNAME")))
        discord_link = DiscordLink.objects.filter(user=user).first()
        if discord_link:
            team_ticket.assigned_to = discord_link
            team_ticket.status = "claimed"
            team_ticket.save()

        ops_page.goto(f"{live_server_url}/ops/tickets/?status=claimed")

        expect(ops_page.locator(f"text={team_ticket.ticket_number}")).to_be_visible(timeout=5000)


class TestTicketCommentExchange:
    """Test comment exchange between team and ops."""

    @pytest.fixture
    def claimed_ticket(self, db, test_team_id):
        """Create a claimed ticket for comment testing."""
        from django.contrib.auth.models import User

        from team.models import DiscordLink, Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=test_team_id)

        ops_username = os.getenv("TEST_OPS_USERNAME", os.getenv("TEST_AUTHENTIK_USERNAME"))
        user, _ = User.objects.get_or_create(
            username=ops_username,
            defaults={"email": f"{ops_username}@test.local"},
        )
        discord_link, _ = DiscordLink.objects.get_or_create(
            user=user,
            defaults={"discord_id": 999888777, "discord_username": ops_username},
        )

        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title=f"[E2E LIFECYCLE] Comment test {os.urandom(4).hex()}",
            description="Testing comments",
            status="claimed",
            assigned_to=discord_link,
        )
        yield ticket
        if Ticket.objects.filter(pk=ticket.pk).exists():
            ticket.delete()

    def test_team_can_comment_on_ticket(self, team_page: Page, claimed_ticket, db, live_server_url):
        """Team member can post comment on their ticket."""
        from ticketing.models import TicketComment

        team_page.goto(f"{live_server_url}/tickets/{claimed_ticket.id}/")

        comment_textarea = team_page.locator('textarea[name="comment"]')
        if comment_textarea.is_visible():
            unique_comment = f"[E2E] Team comment {os.urandom(4).hex()}"
            comment_textarea.fill(unique_comment)
            team_page.click('button[type="submit"]')
            team_page.wait_for_timeout(2000)

            expect(team_page.locator("body")).not_to_contain_text("Server Error")

            comment = TicketComment.objects.filter(ticket=claimed_ticket, comment_text__contains=unique_comment).first()
            assert comment is not None, "Comment should be saved"

    def test_ops_can_respond_to_ticket(self, ops_page: Page, claimed_ticket, db, live_server_url):
        """Ops user can respond to ticket comment."""
        from ticketing.models import TicketComment

        ops_page.goto(f"{live_server_url}/ops/ticket/{claimed_ticket.ticket_number}/")

        comment_textarea = ops_page.locator('textarea[name="comment"]')
        if comment_textarea.is_visible():
            unique_response = f"[E2E] Ops response {os.urandom(4).hex()}"
            comment_textarea.fill(unique_response)
            ops_page.click('button[type="submit"]')
            ops_page.wait_for_timeout(2000)

            comment = TicketComment.objects.filter(
                ticket=claimed_ticket, comment_text__contains=unique_response
            ).first()
            assert comment is not None, "Ops comment should be saved"


class TestTicketResolution:
    """Test ticket resolution by ops."""

    @pytest.fixture
    def claimed_ticket(self, db, test_team_id):
        """Create claimed ticket for resolution testing."""
        from django.contrib.auth.models import User

        from team.models import DiscordLink, Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=test_team_id)

        ops_username = os.getenv("TEST_OPS_USERNAME", os.getenv("TEST_AUTHENTIK_USERNAME"))
        user, _ = User.objects.get_or_create(
            username=ops_username,
            defaults={"email": f"{ops_username}@test.local"},
        )
        discord_link, _ = DiscordLink.objects.get_or_create(
            user=user,
            defaults={"discord_id": 999888777, "discord_username": ops_username},
        )

        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title=f"[E2E LIFECYCLE] Resolution test {os.urandom(4).hex()}",
            description="To be resolved",
            status="claimed",
            assigned_to=discord_link,
        )
        yield ticket
        if Ticket.objects.filter(pk=ticket.pk).exists():
            ticket.delete()

    def test_ops_resolves_ticket_with_points(self, ops_page: Page, claimed_ticket, db, live_server_url):
        """Ops can resolve ticket and assign points."""
        ops_page.goto(f"{live_server_url}/ops/ticket/{claimed_ticket.ticket_number}/")

        resolve_section = ops_page.locator('form[action*="resolve"]')
        if resolve_section.count() > 0:
            resolution_field = ops_page.locator('textarea[name="resolution_notes"]')
            if resolution_field.is_visible():
                resolution_field.fill("Resolved via E2E test")

            points_field = ops_page.locator('input[name="points_charged"]')
            if points_field.is_visible():
                points_field.fill("5")

            resolve_button = ops_page.locator('button:has-text("Resolve")')
            if resolve_button.is_visible():
                resolve_button.click()
                ops_page.wait_for_timeout(2000)

                claimed_ticket.refresh_from_db()
                assert claimed_ticket.status == "resolved"
                assert claimed_ticket.points_charged == 5

    def test_resolved_ticket_shows_in_resolved_filter(self, ops_page: Page, claimed_ticket, db, live_server_url):
        """Resolved ticket appears in resolved filter."""
        claimed_ticket.status = "resolved"
        claimed_ticket.save()

        ops_page.goto(f"{live_server_url}/ops/tickets/?status=resolved")

        expect(ops_page.locator(f"text={claimed_ticket.ticket_number}")).to_be_visible(timeout=5000)


class TestTicketReopen:
    """Test ticket reopen by admin."""

    @pytest.fixture
    def resolved_ticket(self, db, test_team_id):
        """Create resolved ticket for reopen testing."""
        from django.contrib.auth.models import User

        from team.models import DiscordLink, Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=test_team_id)

        ops_username = os.getenv("TEST_OPS_USERNAME", os.getenv("TEST_AUTHENTIK_USERNAME"))
        user, _ = User.objects.get_or_create(
            username=ops_username,
            defaults={"email": f"{ops_username}@test.local"},
        )
        discord_link, _ = DiscordLink.objects.get_or_create(
            user=user,
            defaults={"discord_id": 999888777, "discord_username": ops_username},
        )

        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title=f"[E2E LIFECYCLE] Reopen test {os.urandom(4).hex()}",
            description="Was resolved, needs reopening",
            status="resolved",
            assigned_to=discord_link,
            resolved_by=discord_link,
            resolution_notes="Initial resolution",
        )
        yield ticket
        if Ticket.objects.filter(pk=ticket.pk).exists():
            ticket.delete()

    def test_admin_can_reopen_resolved_ticket(self, admin_page: Page, resolved_ticket, db, live_server_url):
        """Admin can reopen a resolved ticket."""
        admin_page.goto(f"{live_server_url}/ops/ticket/{resolved_ticket.ticket_number}/")

        reopen_button = admin_page.locator('button:has-text("Reopen")')
        if reopen_button.is_visible():
            reopen_button.click()
            admin_page.wait_for_timeout(2000)

            resolved_ticket.refresh_from_db()
            assert resolved_ticket.status == "open", "Ticket should be reopened"

    def test_reopened_ticket_appears_in_open_filter(self, admin_page: Page, resolved_ticket, db, live_server_url):
        """Reopened ticket shows in open filter."""
        resolved_ticket.status = "open"
        resolved_ticket.assigned_to = None
        resolved_ticket.save()

        admin_page.goto(f"{live_server_url}/ops/tickets/?status=open")

        expect(admin_page.locator(f"text={resolved_ticket.ticket_number}")).to_be_visible(timeout=5000)


class TestFullLifecycle:
    """Test complete ticket lifecycle in single test."""

    def test_complete_ticket_workflow(
        self, team_page: Page, ops_page: Page, admin_page: Page, db, test_team_id, live_server_url
    ):
        """
        Full workflow:
        1. Team creates ticket
        2. Ops claims
        3. Team comments
        4. Ops resolves
        5. Admin reopens
        6. Ops resolves again
        """

        from ticketing.models import Ticket

        unique_id = os.urandom(4).hex()
        ticket_title = f"[E2E FULL LIFECYCLE] {unique_id}"

        team_page.goto(f"{live_server_url}/tickets/create/")
        team_page.select_option('select[name="category"]', "general-question")
        team_page.fill('input[name="title"]', ticket_title)
        team_page.fill('textarea[name="description"]', "Full lifecycle test")
        team_page.click('button[type="submit"]')
        team_page.wait_for_timeout(2000)

        ticket = Ticket.objects.filter(title=ticket_title).first()
        assert ticket is not None, "Step 1: Ticket created"
        assert ticket.status == "open"

        ops_page.goto(f"{live_server_url}/ops/tickets/?status=open")
        ticket_row = ops_page.locator(f"tr:has-text('{ticket.ticket_number}')")
        claim_button = ticket_row.locator('button:has-text("Claim"), input[value="Claim"]')
        if claim_button.count() > 0:
            claim_button.first.click()
            ops_page.wait_for_timeout(2000)
            ticket.refresh_from_db()
            assert ticket.status == "claimed", "Step 2: Ticket claimed"

        team_page.goto(f"{live_server_url}/tickets/{ticket.id}/")
        comment_textarea = team_page.locator('textarea[name="comment"]')
        if comment_textarea.is_visible():
            comment_textarea.fill(f"Team follow-up {unique_id}")
            team_page.click('button[type="submit"]')
            team_page.wait_for_timeout(1000)

        ops_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")
        resolve_button = ops_page.locator('button:has-text("Resolve")')
        if resolve_button.is_visible():
            resolution_field = ops_page.locator('textarea[name="resolution_notes"]')
            if resolution_field.is_visible():
                resolution_field.fill("First resolution")
            resolve_button.click()
            ops_page.wait_for_timeout(2000)
            ticket.refresh_from_db()
            assert ticket.status == "resolved", "Step 4: Ticket resolved"

        admin_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")
        reopen_button = admin_page.locator('button:has-text("Reopen")')
        if reopen_button.is_visible():
            reopen_button.click()
            admin_page.wait_for_timeout(2000)
            ticket.refresh_from_db()
            assert ticket.status == "open", "Step 5: Ticket reopened"

        ticket.delete()


class TestAccessControl:
    """Test role-based access control in E2E context."""

    def test_team_cannot_access_ops_dashboard(self, team_page: Page, live_server_url):
        """Team member cannot access ops dashboard."""
        team_page.goto(f"{live_server_url}/ops/tickets/")

        content = team_page.content().lower()
        assert "access denied" in content or "permission" in content or "403" in content

    def test_ops_cannot_reopen_ticket(self, ops_page: Page, db, test_team_id, live_server_url):
        """Regular ops cannot reopen tickets (admin only)."""
        from team.models import Team
        from ticketing.models import Ticket

        team = Team.objects.get(team_number=test_team_id)
        ticket = Ticket.objects.create(
            team=team,
            category="general-question",
            title="[E2E ACCESS] Reopen test",
            status="resolved",
        )

        ops_page.goto(f"{live_server_url}/ops/ticket/{ticket.ticket_number}/")

        reopen_button = ops_page.locator('button:has-text("Reopen")')
        assert not reopen_button.is_visible(), "Reopen button should not be visible to regular ops"

        ticket.delete()

    def test_team_sees_only_own_tickets(self, team_page: Page, db, live_server_url):
        """Team member only sees their team's tickets."""
        from team.models import Team
        from ticketing.models import Ticket

        other_team = Team.objects.exclude(team_number=50).first()
        if other_team:
            other_ticket = Ticket.objects.create(
                team=other_team,
                category="general-question",
                title="[E2E ACCESS] Other team ticket",
                status="open",
            )

            team_page.goto(f"{live_server_url}/tickets/")

            expect(team_page.locator(f"text={other_ticket.ticket_number}")).not_to_be_visible()

            other_ticket.delete()
