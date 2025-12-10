"""
Comprehensive integration tests.

These tests are more thorough and slower. They test full end-to-end workflows,
edge cases, and integration with external services (Authentik, Discord).

Run with: pytest -m integration
"""

import pytest
from django.contrib.auth.models import User
from django.test import Client
from playwright.sync_api import Page, expect

from core.models import UserGroups
from team.models import DiscordLink, Team
from ticketing.models import Ticket

pytestmark = [
    pytest.mark.integration,
]


class TestFullTicketWorkflow:
    """Test complete ticket lifecycle from creation to resolution."""

    @pytest.fixture
    def support_user(self, db):
        """Create support user with proper Authentik permissions."""
        user = User.objects.create_user(
            username="comprehensive_support",
            email="comprehensive_support@example.com",
        )
        UserGroups.objects.create(
            user=user,
            authentik_id="comprehensive_support_uid",
            groups=["WCComps_Ticketing_Support"],
        )
        discord_link = DiscordLink.objects.create(
            user=user,
            discord_id=444444444,
            discord_username="comprehensive_support",
        )
        yield discord_link
        discord_link.delete()
        user.delete()

    def test_complete_ticket_lifecycle_api(self, db, test_team_id, support_user):
        """Test full ticket workflow via API: create -> claim -> comment -> resolve."""
        from django.urls import reverse

        client = Client()
        client.force_login(support_user.user)

        team = Team.objects.get(team_number=test_team_id)

        # Create ticket
        ticket = Ticket.objects.create(
            ticket_number="T-COMPREHENSIVE-001",
            title="[INTEGRATION TEST] Full lifecycle test",
            description="Testing complete workflow",
            team=team,
            status="open",
        )

        try:
            # Verify ticket is open
            assert ticket.status == "open"
            assert ticket.assigned_to is None

            # Claim ticket
            response = client.post(reverse("ops_ticket_claim", kwargs={"ticket_number": ticket.ticket_number}))
            assert response.status_code in [200, 302]

            ticket.refresh_from_db()
            # assigned_to is now User, not DiscordLink
            assert ticket.assigned_to == support_user.user
            assert ticket.status == "claimed"

            # Add comment
            response = client.post(
                reverse("ops_ticket_comment", kwargs={"ticket_number": ticket.ticket_number}),
                data={"comment": "Working on this ticket"},
            )
            assert response.status_code in [200, 302]

            response = client.post(
                reverse("ops_ticket_resolve", kwargs={"ticket_number": ticket.ticket_number}),
                data={
                    "resolution_notes": "Issue resolved successfully",
                    "points": "10",
                },
            )
            assert response.status_code in [200, 302]

            ticket.refresh_from_db()
            assert ticket.status == "resolved"
            assert ticket.resolution_notes == "Issue resolved successfully"

        finally:
            ticket.delete()

    @pytest.mark.browser
    def test_complete_ticket_lifecycle_browser(self, authenticated_page: Page, db, test_team_id, live_server_url):
        """Test full ticket workflow via browser."""
        from integration_tests.conftest import create_test_ticket

        ticket = create_test_ticket("Browser full workflow", team_id=test_team_id)
        base_url = live_server_url

        try:
            # Navigate to ops dashboard
            authenticated_page.goto(f"{base_url}/ops/tickets/")

            # Find ticket
            expect(authenticated_page.locator(f"text={ticket.ticket_number}")).to_be_visible()

            # Click on ticket to view details
            authenticated_page.click(f"text={ticket.ticket_number}")

            # Wait for navigation
            authenticated_page.wait_for_timeout(1000)

            # Should navigate to detail page (check URL contains ticket_number)
            assert ticket.ticket_number in authenticated_page.url or "/ops/ticket" in authenticated_page.url

            # Page should render without errors
            expect(authenticated_page.locator("body")).not_to_contain_text("500")
            expect(authenticated_page.locator("body")).not_to_contain_text("Server Error")

        finally:
            ticket.delete()


class TestAuthentikIntegration:
    """Test real Authentik API integration."""

    @pytest.mark.skip(reason="Authentik client API changed, needs update")
    def test_authentik_client_connection(self, authentik_client):
        """Verify Authentik API client can connect."""
        # The authentik_client package API has changed significantly.
        # This test needs to be updated to use the new CoreApi class.

    @pytest.mark.skip(reason="Authentik client API changed, needs update")
    def test_authentik_group_fetch(self, authentik_client):
        """Test fetching groups from Authentik."""
        # The authentik_client package API has changed significantly.
        # This test needs to be updated to use the new CoreApi class.


class TestDiscordIntegration:
    """Test Discord API integration (if bot is running)."""

    @pytest.mark.skip(reason="Requires Discord bot to be running")
    def test_discord_bot_connection(self, discord_credentials):
        """Verify Discord bot can connect to API."""
        # This would require the bot to be running
        # Skip for now, but placeholder for future enhancement


class TestAttachmentHandling:
    """Test file attachment upload and download."""

    @pytest.fixture
    def support_user(self, db):
        """Create support user."""
        from core.models import UserGroups

        user = User.objects.create_user(
            username="attachment_test_user",
            email="attachment_test@example.com",
        )
        discord_link = DiscordLink.objects.create(
            user=user,
            discord_id=555555555,
            discord_username="attachment_test_user",
        )
        UserGroups.objects.create(
            user=user,
            authentik_id="attachment_test_user_uid",
            groups=["WCComps_Ticketing_Support"],
        )
        yield discord_link
        discord_link.delete()
        user.delete()

    @pytest.fixture
    def test_ticket(self, db, test_team_id):
        """Create test ticket."""
        team = Team.objects.get(team_number=test_team_id)

        ticket = Ticket.objects.create(
            ticket_number="T-ATTACHMENT-001",
            title="[INTEGRATION TEST] Attachment test",
            description="Testing file uploads",
            team=team,
            status="open",
        )

        yield ticket
        ticket.delete()

    @pytest.mark.skip(reason="Attachment upload endpoint not yet implemented")
    def test_attachment_upload(self, db, test_ticket, support_user):
        """Test file attachment upload."""

    def test_attachment_download(self, db, test_ticket, support_user):
        """Test file attachment download."""
        from ticketing.models import TicketAttachment

        client = Client()
        client.force_login(support_user.user)

        # Create attachment using actual model fields
        # TicketAttachment uses file_data (BinaryField) and uploaded_by (CharField)
        attachment = TicketAttachment.objects.create(
            ticket=test_ticket,
            uploaded_by=support_user.discord_username,
            file_data=b"Download test content",
            filename="download_test.txt",
            mime_type="text/plain",
        )

        try:
            from django.urls import reverse

            # Download attachment
            response = client.get(
                reverse(
                    "ops_ticket_attachment_download",
                    kwargs={
                        "ticket_number": test_ticket.ticket_number,
                        "attachment_id": attachment.id,
                    },
                )
            )

            # Should succeed
            assert response.status_code == 200
            assert b"Download test content" in response.content

        finally:
            attachment.delete()


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_nonexistent_ticket(self, db):
        """Accessing nonexistent ticket should return 404, not 500."""
        from django.urls import reverse

        client = Client()

        response = client.get(reverse("ops_ticket_detail", kwargs={"ticket_number": "T-NONEXISTENT-999"}))

        # Should be 404 or 302 (redirect to login), not 500
        assert response.status_code in [404, 302]

    def test_invalid_team_id(self, db):
        """Accessing invalid team should handle gracefully."""
        from django.urls import reverse

        client = Client()

        response = client.get(reverse("ops_school_info_edit", kwargs={"team_number": 9999}))

        # Should be 404 or 302, not 500
        assert response.status_code in [404, 302]

    def test_ticket_claim_twice(self, db, test_team_id):
        """Claiming already claimed ticket should handle gracefully."""
        from django.urls import reverse

        from core.models import UserGroups

        team = Team.objects.get(team_number=test_team_id)

        ticket = Ticket.objects.create(
            ticket_number="T-DOUBLE-CLAIM",
            title="[INTEGRATION TEST] Double claim test",
            description="Test double claim handling",
            team=team,
            status="open",
        )

        try:
            # Create two users with proper ticketing permissions
            user1 = User.objects.create_user(username="claimer1", email="claimer1@example.com")
            discord_link1 = DiscordLink.objects.create(
                user=user1,
                discord_id=666666666,
                discord_username="claimer1",
            )
            UserGroups.objects.create(
                user=user1,
                authentik_id="claimer1_uid",
                groups=["WCComps_Ticketing_Support"],
            )

            user2 = User.objects.create_user(username="claimer2", email="claimer2@example.com")
            discord_link2 = DiscordLink.objects.create(
                user=user2,
                discord_id=777777777,
                discord_username="claimer2",
            )
            UserGroups.objects.create(
                user=user2,
                authentik_id="claimer2_uid",
                groups=["WCComps_Ticketing_Support"],
            )

            # User 1 claims
            client1 = Client()
            client1.force_login(user1)
            response = client1.post(reverse("ops_ticket_claim", kwargs={"ticket_number": ticket.ticket_number}))
            assert response.status_code in [200, 302]

            # User 2 tries to claim
            client2 = Client()
            client2.force_login(user2)
            response = client2.post(reverse("ops_ticket_claim", kwargs={"ticket_number": ticket.ticket_number}))

            # Should handle gracefully (not 500)
            assert response.status_code in [200, 302, 400, 409]

            # Ticket should still be assigned to user 1
            ticket.refresh_from_db()
            assert ticket.assigned_to == user1

            # Cleanup
            discord_link1.delete()
            user1.delete()
            discord_link2.delete()
            user2.delete()

        finally:
            ticket.delete()


class TestDatabaseTransactions:
    """Test database transaction integrity."""

    def test_bulk_operation_rollback_on_error(self, db, test_team_id):
        """Bulk operations should rollback on partial failure."""
        from django.urls import reverse

        from core.models import UserGroups

        team = Team.objects.get(team_number=test_team_id)

        # Create tickets
        tickets = []
        for i in range(3):
            ticket = Ticket.objects.create(
                ticket_number=f"T-ROLLBACK-{i}",
                title=f"[INTEGRATION TEST] Rollback test {i}",
                description="Transaction test",
                team=team,
                status="open",
            )
            tickets.append(ticket)

        try:
            user = User.objects.create_user(
                username="bulk_test_user",
                email="bulk_test@example.com",
            )
            discord_link = DiscordLink.objects.create(
                user=user,
                discord_id=888888888,
                discord_username="bulk_test_user",
            )
            UserGroups.objects.create(
                user=user,
                authentik_id="bulk_test_user_uid",
                groups=["WCComps_Ticketing_Support"],
            )

            client = Client()
            client.force_login(user)

            # Try bulk claim with invalid ticket ID
            ticket_ids = [tickets[0].id, tickets[1].id, 99999]  # Last ID doesn't exist

            response = client.post(
                reverse("ops_tickets_bulk_claim"),
                data={"ticket_ids": ticket_ids},
            )

            # Should handle error gracefully
            assert response.status_code in [200, 302, 400, 404]

            # Either all tickets assigned or none (transaction integrity)
            tickets[0].refresh_from_db()
            tickets[1].refresh_from_db()

            # Both should have same assignment status (atomic)
            if tickets[0].assigned_to is not None:
                assert tickets[1].assigned_to is not None
            else:
                assert tickets[1].assigned_to is None

            # Cleanup
            discord_link.delete()
            user.delete()

        finally:
            for ticket in tickets:
                ticket.delete()
