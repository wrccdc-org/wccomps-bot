"""Integration tests for ticket workflow.

Tests cover the complete end-to-end flow:
1. Ticket creation
2. Support claims ticket
3. Support resolves ticket
4. Ticketing Admin verifies points

These tests verify data integrity and workflow state transitions at the model level.
"""

import os
from collections.abc import Generator

import pytest
from django.contrib.auth.models import User
from django.utils import timezone

from team.models import Team
from ticketing.models import Ticket, TicketHistory

pytestmark = pytest.mark.django_db


@pytest.fixture(scope="session", autouse=True)
def enable_ticketing() -> Generator[None, None, None]:
    """Enable ticketing for all tests in this module."""
    os.environ["TICKETING_ENABLED"] = "true"
    yield
    os.environ.pop("TICKETING_ENABLED", None)


@pytest.fixture
def setup_team():
    """Create test team."""
    team = Team.objects.create(
        team_name="Test Team",
        team_number=1,
        max_members=10,
        ticket_counter=0,
    )
    return team


@pytest.fixture
def setup_users():
    """Create test users with Person records."""
    team_user = User.objects.create_user(username="team_user", password="test123")
    support_user = User.objects.create_user(username="support_user", password="test123")
    admin_user = User.objects.create_user(username="admin_user", password="test123")

    # Update Person records (auto-created by signal)
    support_user.person.discord_id = 123456789
    support_user.person.discord_username = "support_staff"
    support_user.person.save()

    return {
        "team": team_user,
        "support": support_user,
        "admin": admin_user,
    }


class TestTicketWorkflow:
    """Test complete ticket workflow from creation to point verification."""

    def test_step1_ticket_created(self, setup_team, setup_users):
        """Step 1: Ticket created - verify initial state."""
        team = setup_team

        # Create ticket (simulating Discord bot creation)
        ticket = Ticket.objects.create(
            ticket_number="T001-001",
            team=team,
            category="box-reset",
            title="Need web server reset",
            description="Web server is not responding",
            status="open",
        )

        # Verify initial workflow state
        assert ticket.status == "open"
        assert ticket.team == team
        assert ticket.assigned_to is None
        assert ticket.resolved_by is None
        assert ticket.points_charged == 0
        assert ticket.points_verified is False

    def test_step2_support_claims_ticket(self, setup_team, setup_users):
        """Step 2: Support claims ticket - verify claim state."""
        team = setup_team
        users = setup_users
        support_person = users["support"].person

        # Create open ticket
        ticket = Ticket.objects.create(
            ticket_number="T001-002",
            team=team,
            category="scoring-service-check",
            title="Service check issue",
            description="Service showing down but is up",
            status="open",
        )

        # Support claims ticket
        ticket.status = "claimed"
        ticket.assigned_to = support_person
        ticket.assigned_at = timezone.now()
        ticket.save()

        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            action="claimed",
            actor=support_person,
            details={"assigned_to": str(support_person)},
        )

        # Verify ticket was claimed
        ticket.refresh_from_db()
        assert ticket.status == "claimed"
        assert ticket.assigned_to == support_person
        assert ticket.assigned_at is not None

        # Verify history entry was created
        history = TicketHistory.objects.filter(ticket=ticket, action="claimed").first()
        assert history is not None
        assert history.actor == support_person

    def test_step3_support_resolves_ticket(self, setup_team, setup_users):
        """Step 3: Support resolves ticket - verify resolution state."""
        team = setup_team
        users = setup_users
        support_person = users["support"].person

        # Create claimed ticket
        ticket = Ticket.objects.create(
            ticket_number="T001-003",
            team=team,
            category="box-reset",
            title="Database server reset",
            description="Database is unresponsive",
            status="claimed",
            assigned_to=support_person,
            assigned_at=timezone.now(),
        )

        # Support resolves ticket
        ticket.status = "resolved"
        ticket.resolved_by = support_person
        ticket.resolved_at = timezone.now()
        ticket.resolution_notes = "Reset database server successfully"
        ticket.duration_notes = "15 minutes"
        ticket.points_charged = 60
        ticket.save()

        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            action="resolved",
            actor=support_person,
            details={"points_charged": 60},
        )

        # Verify ticket was resolved
        ticket.refresh_from_db()
        assert ticket.status == "resolved"
        assert ticket.resolved_by == support_person
        assert ticket.resolved_at is not None
        assert ticket.points_charged == 60
        assert ticket.points_verified is False

        # Verify history entry was created
        history = TicketHistory.objects.filter(ticket=ticket, action="resolved").first()
        assert history is not None

    def test_step4_ticketing_admin_verifies_points(self, setup_team, setup_users):
        """Step 4: Ticketing Admin verifies points."""
        team = setup_team
        users = setup_users
        support_person = users["support"].person

        # Create resolved ticket
        ticket = Ticket.objects.create(
            ticket_number="T001-004",
            team=team,
            category="blackteam-phone-consultation",
            title="Phone consultation",
            description="Need help with firewall rules",
            status="resolved",
            assigned_to=support_person,
            assigned_at=timezone.now(),
            resolved_by=support_person,
            resolved_at=timezone.now(),
            resolution_notes="Provided firewall assistance",
            points_charged=100,
            points_verified=False,
        )

        # Admin verifies points
        ticket.points_verified = True
        ticket.points_verified_by = users["admin"]
        ticket.points_verified_at = timezone.now()
        ticket.verification_notes = "Appropriate point charge for consultation"
        ticket.save()

        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            action="points_verified",
            details={"verified_by": users["admin"].username, "points_charged": 100},
        )

        # Verify points verification was recorded
        ticket.refresh_from_db()
        assert ticket.points_verified is True
        assert ticket.points_verified_by == users["admin"]
        assert ticket.points_verified_at is not None
        assert ticket.verification_notes == "Appropriate point charge for consultation"

        # Verify history entry was created
        history = TicketHistory.objects.filter(ticket=ticket, action="points_verified").first()
        assert history is not None

    def test_step5_complete_workflow_end_to_end(self, setup_team, setup_users):
        """Step 5: Complete workflow from creation to verification."""
        team = setup_team
        users = setup_users

        # Create another support person for this test
        support2_user = User.objects.create_user(username="support_person2", password="test123")
        support2_person = support2_user.person
        support2_person.discord_id = 987654321
        support2_person.discord_username = "support_person"
        support2_person.save()

        # Step 1: Ticket created
        ticket = Ticket.objects.create(
            ticket_number="T001-005",
            team=team,
            category="scoring-service-check",
            title="Complete workflow test",
            description="Testing full lifecycle",
            status="open",
        )
        assert ticket.status == "open"

        # Step 2: Support claims ticket
        ticket.status = "claimed"
        ticket.assigned_to = support2_person
        ticket.assigned_at = timezone.now()
        ticket.save()

        TicketHistory.objects.create(
            ticket=ticket,
            action="claimed",
            actor=support2_person,
        )

        ticket.refresh_from_db()
        assert ticket.status == "claimed"
        assert ticket.assigned_to == support2_person

        # Step 3: Support resolves ticket
        ticket.status = "resolved"
        ticket.resolved_by = support2_person
        ticket.resolved_at = timezone.now()
        ticket.resolution_notes = "Verified service is working correctly"
        ticket.duration_notes = "10 minutes"
        ticket.points_charged = 10
        ticket.save()

        TicketHistory.objects.create(
            ticket=ticket,
            action="resolved",
            actor=support2_person,
            details={"points_charged": 10},
        )

        ticket.refresh_from_db()
        assert ticket.status == "resolved"
        assert ticket.points_charged == 10
        assert ticket.points_verified is False

        # Step 4: Admin verifies points
        ticket.points_verified = True
        ticket.points_verified_by = users["admin"]
        ticket.points_verified_at = timezone.now()
        ticket.verification_notes = "Points verified"
        ticket.save()

        TicketHistory.objects.create(
            ticket=ticket,
            action="points_verified",
            details={"verified_by": users["admin"].username, "points_charged": 10},
        )

        ticket.refresh_from_db()
        assert ticket.points_verified is True
        assert ticket.points_verified_by == users["admin"]

        # Verify data integrity throughout workflow
        assert ticket.ticket_number == "T001-005"
        assert ticket.team == team
        assert ticket.status == "resolved"
        assert ticket.points_charged == 10
        assert ticket.points_verified is True

        # Verify all history entries exist
        history_entries = TicketHistory.objects.filter(ticket=ticket).order_by("timestamp")
        assert history_entries.count() == 3
        actions = [h.action for h in history_entries]
        assert "claimed" in actions
        assert "resolved" in actions
        assert "points_verified" in actions

    def test_step6_ticket_state_query(self, setup_team, setup_users):
        """Step 6: Verify ticket state queries work correctly."""
        team = setup_team
        users = setup_users

        # Create tickets in different states
        open_ticket = Ticket.objects.create(
            ticket_number="T001-010",
            team=team,
            category="other",
            title="Open ticket",
            status="open",
        )

        resolved_unverified = Ticket.objects.create(
            ticket_number="T001-011",
            team=team,
            category="box-reset",
            title="Resolved but not verified",
            status="resolved",
            points_charged=50,
            points_verified=False,
            resolved_at=timezone.now(),
        )

        resolved_verified = Ticket.objects.create(
            ticket_number="T001-012",
            team=team,
            category="box-reset",
            title="Resolved and verified",
            status="resolved",
            points_charged=30,
            points_verified=True,
            points_verified_by=users["admin"],
            points_verified_at=timezone.now(),
            resolved_at=timezone.now(),
        )

        # Verify query filters work correctly
        open_tickets = Ticket.objects.filter(status="open")
        assert open_ticket in open_tickets
        assert resolved_unverified not in open_tickets

        unverified_resolved = Ticket.objects.filter(status="resolved", points_verified=False)
        assert resolved_unverified in unverified_resolved
        assert resolved_verified not in unverified_resolved

        verified_tickets = Ticket.objects.filter(points_verified=True)
        assert resolved_verified in verified_tickets
        assert resolved_unverified not in verified_tickets
