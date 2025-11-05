"""Tests for ticket dashboard functionality."""

from unittest.mock import AsyncMock, MagicMock
import discord
import pytest
from django.test import TestCase
from core.models import Team, Ticket
from bot.ticket_dashboard import (
    format_ticket_embed,
    get_ticket_color,
    post_ticket_to_dashboard,
    update_ticket_dashboard,
)


class TestTicketColor:
    """Test ticket color helper function."""

    def test_get_ticket_color_open(self) -> None:
        """Test color for open tickets."""
        assert get_ticket_color("open") == discord.Color.red()

    def test_get_ticket_color_claimed(self) -> None:
        """Test color for claimed tickets."""
        assert get_ticket_color("claimed") == discord.Color.orange()

    def test_get_ticket_color_resolved(self) -> None:
        """Test color for resolved tickets."""
        assert get_ticket_color("resolved") == discord.Color.green()

    def test_get_ticket_color_cancelled(self) -> None:
        """Test color for cancelled tickets."""
        assert get_ticket_color("cancelled") == discord.Color.dark_gray()

    def test_get_ticket_color_unknown(self) -> None:
        """Test color for unknown status."""
        assert get_ticket_color("unknown") == discord.Color.default()


@pytest.mark.django_db(transaction=True)
class TicketDashboardTest(TestCase):
    """Test ticket dashboard embed generation."""

    def setUp(self) -> None:
        self.team = Team.objects.create(
            team_number=40,
            team_name="Test Team",
            authentik_group="test-group",
        )

    def test_format_ticket_embed_basic(self) -> None:
        """Test formatting a basic ticket embed."""
        ticket = Ticket.objects.create(
            ticket_number="T001-001",
            team=self.team,
            category="box-reset",
            title="Test Ticket",
            description="Test description",
            status="open",
        )

        # Should not raise AttributeError
        embed = format_ticket_embed(ticket)

        self.assertIsNotNone(embed)
        self.assertIsNotNone(embed.title)
        assert embed.title is not None
        self.assertIn("Test Ticket", embed.title)
        self.assertEqual(embed.description, "Test description")

    def test_format_ticket_embed_with_assignment(self) -> None:
        """Test formatting ticket with assigned volunteer."""
        ticket = Ticket.objects.create(
            ticket_number="T001-002",
            team=self.team,
            category="scoring-service-check",
            title="Service Check",
            description="Check DNS",
            status="claimed",
            assigned_to_discord_id=123456789,
            assigned_to_discord_username="volunteer1",
        )

        embed = format_ticket_embed(ticket)

        self.assertIsNotNone(embed)
        # Check that assigned field is included
        field_names = [field.name for field in embed.fields]
        self.assertIn("Assigned To", field_names)

    def test_format_ticket_embed_resolved(self) -> None:
        """Test formatting resolved ticket."""
        from django.utils import timezone as tz

        ticket = Ticket.objects.create(
            ticket_number="T001-003",
            team=self.team,
            category="other",
            title="General Issue",
            description="Fixed issue",
            status="resolved",
            resolved_at=tz.now(),
            resolved_by_discord_id=987654321,
            resolved_by_discord_username="admin1",
            resolution_notes="All fixed",
            points_charged=10,
        )

        embed = format_ticket_embed(ticket)

        self.assertIsNotNone(embed)
        field_names = [field.name for field in embed.fields]
        self.assertIn("Resolved At", field_names)

    def test_format_ticket_embed_all_categories(self) -> None:
        """Test all ticket categories can be formatted without errors."""
        from core.tickets_config import TICKET_CATEGORIES

        for idx, category_key in enumerate(TICKET_CATEGORIES.keys(), start=10):
            ticket = Ticket.objects.create(
                ticket_number=f"T001-{idx:03d}",
                team=self.team,
                category=category_key,
                title=f"Test {category_key}",
                description="Test",
                status="open",
            )

            # Should not raise AttributeError on missing fields
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
