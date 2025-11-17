"""
Comprehensive integration tests.

These tests are more thorough and slower. They test full end-to-end workflows,
edge cases, and integration with external services (Authentik, Discord).

Run with: pytest -m integration
"""

import os

import pytest
from django.contrib.auth.models import User
from django.test import Client
from playwright.sync_api import Page, expect

from person.models import Person
from team.models import Team
from ticketing.models import Ticket

TICKETING_ENABLED = os.environ.get("TICKETING_ENABLED", "false").lower() == "true"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not TICKETING_ENABLED, reason="Ticketing not enabled"),
]


class TestFullTicketWorkflow:
    """Test complete ticket lifecycle from creation to resolution."""

    @pytest.fixture
    def support_user(self, db):
        """Create support user."""
        user = User.objects.create_user(
            username="comprehensive_support",
            email="comprehensive_support@example.com",
        )
        person = Person.objects.create(
            user=user,
            discord_id="444444444",
            authentik_username="comprehensive_support",
        )
        yield person
        person.delete()
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
            assert ticket.claimed_by is None

            # Claim ticket
            response = client.post(reverse("ops_ticket_claim", kwargs={"ticket_number": ticket.ticket_number}))
            assert response.status_code in [200, 302]

            ticket.refresh_from_db()
            assert ticket.claimed_by == support_user
            assert ticket.status == "open"  # Still open after claim

            # Add comment
            response = client.post(
                reverse("ops_ticket_comment", kwargs={"ticket_number": ticket.ticket_number}),
                data={"comment": "Working on this ticket"},
            )
            assert response.status_code in [200, 302]

            # Resolve ticket
            response = client.post(
                reverse("ops_ticket_resolve", kwargs={"ticket_number": ticket.ticket_number}),
                data={
                    "resolution": "Issue resolved successfully",
                    "points": "10",
                },
            )
            assert response.status_code in [200, 302]

            ticket.refresh_from_db()
            assert ticket.status == "resolved"
            assert ticket.resolution == "Issue resolved successfully"

        finally:
            ticket.delete()

    @pytest.mark.browser
    def test_complete_ticket_lifecycle_browser(self, authenticated_page: Page, db, test_team_id):
        """Test full ticket workflow via browser."""
        from conftest import create_test_ticket

        ticket = create_test_ticket("Browser full workflow", team_number=test_team_id)
        base_url = os.getenv("TEST_BASE_URL", "http://localhost:8000")

        try:
            # Navigate to ops dashboard
            authenticated_page.goto(f"{base_url}/ops/tickets/")

            # Find ticket
            expect(authenticated_page.locator(f"text={ticket.ticket_number}")).to_be_visible()

            # Click on ticket to view details
            authenticated_page.click(f"text={ticket.ticket_number}")

            # Should navigate to detail page
            expect(authenticated_page).to_have_url(f"**/ops/ticket/{ticket.ticket_number}/**")

            # Page should render without errors
            expect(authenticated_page).not_to_have_text("500")
            expect(authenticated_page).not_to_have_text("Server Error")

        finally:
            ticket.delete()


class TestAuthentikIntegration:
    """Test real Authentik API integration."""

    def test_authentik_client_connection(self, authentik_client):
        """Verify Authentik API client can connect."""
        from authentik_client.api.core import core_users_list

        # Try to list users (requires API token with permissions)
        try:
            response = core_users_list.sync_detailed(client=authentik_client, page_size=1)
            assert response.status_code in [200, 403]  # 200 if authorized, 403 if not
        except Exception as e:
            pytest.fail(f"Authentik API connection failed: {e}")

    def test_authentik_group_fetch(self, authentik_client):
        """Test fetching groups from Authentik."""
        from authentik_client.api.core import core_groups_list

        try:
            response = core_groups_list.sync_detailed(client=authentik_client, page_size=10)
            assert response.status_code in [200, 403]

            if response.status_code == 200:
                # Verify we can parse the response
                assert response.parsed is not None

        except Exception as e:
            pytest.fail(f"Failed to fetch Authentik groups: {e}")


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
        user = User.objects.create_user(
            username="attachment_test_user",
            email="attachment_test@example.com",
        )
        person = Person.objects.create(
            user=user,
            discord_id="555555555",
            authentik_username="attachment_test_user",
        )
        yield person
        person.delete()
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

    def test_attachment_upload(self, db, test_ticket, support_user):
        """Test file attachment upload."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse

        client = Client()
        client.force_login(support_user.user)

        # Create a test file
        test_file = SimpleUploadedFile(
            "test.txt",
            b"This is a test attachment file",
            content_type="text/plain",
        )

        # Upload attachment
        response = client.post(
            reverse(
                "ops_ticket_attachment_upload",
                kwargs={"ticket_number": test_ticket.ticket_number},
            ),
            data={"file": test_file},
            format="multipart",
        )

        # Should succeed
        assert response.status_code in [200, 302]

        # Verify attachment was created
        from ticketing.models import TicketAttachment

        attachments = TicketAttachment.objects.filter(ticket=test_ticket)
        assert attachments.count() > 0

        # Cleanup
        for attachment in attachments:
            if attachment.file:
                attachment.file.delete()
            attachment.delete()

    def test_attachment_download(self, db, test_ticket, support_user):
        """Test file attachment download."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse

        from ticketing.models import TicketAttachment

        client = Client()
        client.force_login(support_user.user)

        # Create attachment
        test_file = SimpleUploadedFile(
            "download_test.txt",
            b"Download test content",
            content_type="text/plain",
        )

        attachment = TicketAttachment.objects.create(
            ticket=test_ticket,
            uploaded_by=support_user,
            file=test_file,
            filename="download_test.txt",
        )

        try:
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
            if attachment.file:
                attachment.file.delete()
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

        team = Team.objects.get(team_number=test_team_id)

        ticket = Ticket.objects.create(
            ticket_number="T-DOUBLE-CLAIM",
            title="[INTEGRATION TEST] Double claim test",
            description="Test double claim handling",
            team=team,
            status="open",
        )

        try:
            # Create two users
            user1 = User.objects.create_user(username="claimer1", email="claimer1@example.com")
            person1 = Person.objects.create(
                user=user1,
                discord_id="666666666",
                authentik_username="claimer1",
            )

            user2 = User.objects.create_user(username="claimer2", email="claimer2@example.com")
            person2 = Person.objects.create(
                user=user2,
                discord_id="777777777",
                authentik_username="claimer2",
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

            # Ticket should still be claimed by user 1
            ticket.refresh_from_db()
            assert ticket.claimed_by == person1

            # Cleanup
            person1.delete()
            user1.delete()
            person2.delete()
            user2.delete()

        finally:
            ticket.delete()


class TestDatabaseTransactions:
    """Test database transaction integrity."""

    def test_bulk_operation_rollback_on_error(self, db, test_team_id):
        """Bulk operations should rollback on partial failure."""
        from django.urls import reverse

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
            person = Person.objects.create(
                user=user,
                discord_id="888888888",
                authentik_username="bulk_test_user",
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

            # Either all tickets claimed or none (transaction integrity)
            tickets[0].refresh_from_db()
            tickets[1].refresh_from_db()

            # Both should have same claim status (atomic)
            if tickets[0].claimed_by is not None:
                assert tickets[1].claimed_by is not None
            else:
                assert tickets[1].claimed_by is None

            # Cleanup
            person.delete()
            user.delete()

        finally:
            for ticket in tickets:
                ticket.delete()
