"""Tests for ticket dashboard functionality."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from django.test import TestCase
from team.models import Team
from ticketing.models import Ticket
from bot.ticket_dashboard import (
    format_ticket_embed,
    post_ticket_to_dashboard,
    update_ticket_dashboard,
)


@pytest.mark.django_db(transaction=True)
class TicketDashboardTest(TestCase):
    """Test ticket dashboard embed generation."""

    def setUp(self) -> None:
        self.team = Team.objects.create(
            team_number=40,
            team_name="Test Team",
            authentik_group="test-group",
        )

    def test_format_ticket_embed_comprehensive(self) -> None:
        """Test formatting ticket embeds with various states and categories."""
        from django.utils import timezone as tz
        from core.tickets_config import TICKET_CATEGORIES

        # Test basic open ticket
        open_ticket = Ticket.objects.create(
            ticket_number="T001-001",
            team=self.team,
            category="box-reset",
            title="Test Open",
            description="Open description",
            status="open",
        )
        open_embed = format_ticket_embed(open_ticket)
        self.assertIsNotNone(open_embed)
        self.assertIn("Test Open", str(open_embed.title))

        # Test claimed ticket with assignment
        claimed_ticket = Ticket.objects.create(
            ticket_number="T001-002",
            team=self.team,
            category="scoring-service-check",
            title="Test Claimed",
            description="Claimed description",
            status="claimed",
            assigned_to_discord_id=123456789,
            assigned_to_discord_username="volunteer1",
        )
        claimed_embed = format_ticket_embed(claimed_ticket)
        field_names = [field.name for field in claimed_embed.fields]
        self.assertIn("Assigned To", field_names)

        # Test resolved ticket with resolution info
        resolved_ticket = Ticket.objects.create(
            ticket_number="T001-003",
            team=self.team,
            category="other",
            title="Test Resolved",
            description="Resolved description",
            status="resolved",
            resolved_at=tz.now(),
            resolved_by_discord_id=987654321,
            resolved_by_discord_username="admin1",
            resolution_notes="All fixed",
            points_charged=10,
        )
        resolved_embed = format_ticket_embed(resolved_ticket)
        resolved_field_names = [field.name for field in resolved_embed.fields]
        self.assertIn("Resolved At", resolved_field_names)

        # Test that all ticket categories can be formatted
        for idx, category_key in enumerate(TICKET_CATEGORIES.keys(), start=10):
            ticket = Ticket.objects.create(
                ticket_number=f"T001-{idx:03d}",
                team=self.team,
                category=category_key,
                title=f"Test {category_key}",
                description="Test",
                status="open",
            )
            embed = format_ticket_embed(ticket)
            self.assertIsNotNone(embed)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestDashboardUpdate:
    """Test dashboard update functions."""

    async def test_post_ticket_to_dashboard_with_unified_dashboard(self) -> None:
        """Test posting ticket when unified dashboard exists."""
        bot = MagicMock()
        unified_dashboard = AsyncMock()
        unified_dashboard.trigger_update = AsyncMock()
        bot.unified_dashboard = unified_dashboard

        team = await Team.objects.acreate(
            team_number=27, team_name="Test Team", authentik_group="test"
        )
        ticket = await Ticket.objects.acreate(
            ticket_number="T001",
            team=team,
            category="box-reset",
            title="Test",
            description="Test",
            status="open",
        )

        await post_ticket_to_dashboard(bot, ticket)

        unified_dashboard.trigger_update.assert_called_once()

    async def test_post_ticket_to_dashboard_no_unified_dashboard(self) -> None:
        """Test posting ticket when unified dashboard doesn't exist."""
        bot = MagicMock()
        bot.unified_dashboard = None

        team = await Team.objects.acreate(
            team_number=28, team_name="Test Team", authentik_group="test"
        )
        ticket = await Ticket.objects.acreate(
            ticket_number="T002",
            team=team,
            category="box-reset",
            title="Test",
            description="Test",
            status="open",
        )

        await post_ticket_to_dashboard(bot, ticket)

    async def test_update_ticket_dashboard_with_unified_dashboard(self) -> None:
        """Test updating dashboard when unified dashboard exists."""
        bot = MagicMock()
        unified_dashboard = AsyncMock()
        unified_dashboard.trigger_update = AsyncMock()
        bot.unified_dashboard = unified_dashboard

        team = await Team.objects.acreate(
            team_number=29, team_name="Test Team", authentik_group="test"
        )
        ticket = await Ticket.objects.acreate(
            ticket_number="T003",
            team=team,
            category="box-reset",
            title="Test",
            description="Test",
            status="open",
        )

        await update_ticket_dashboard(bot, ticket)

        unified_dashboard.trigger_update.assert_called_once()
