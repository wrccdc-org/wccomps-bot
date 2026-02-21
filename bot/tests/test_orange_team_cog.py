"""Tests for Orange Team cog commands."""

import random
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
import pytest_asyncio
from django.contrib.auth.models import User
from scoring.models import OrangeTeamScore

from bot.cogs.orange_team import OrangeTeamCog
from core.models import UserGroups
from team.models import DiscordLink, Team


@pytest_asyncio.fixture
async def orange_team_user(db) -> User:
    """Create a user with Orange Team permissions."""
    unique_id = str(uuid.uuid4())[:8]
    username = f"orangeuser_{unique_id}"
    discord_id = random.randint(100000000000000000, 999999999999999999)

    user = await User.objects.acreate(
        username=username,
        email=f"orange_{unique_id}@test.com",
    )

    await UserGroups.objects.acreate(
        user=user,
        authentik_id=f"test-orange-uid-{unique_id}",
        groups=["WCComps_OrangeTeam"],
    )

    await DiscordLink.objects.acreate(
        user=user,
        discord_id=discord_id,
        discord_username=username,
        is_active=True,
    )

    user._discord_id = discord_id
    return user


@pytest_asyncio.fixture
async def gold_team_user(db) -> User:
    """Create a user with Gold Team permissions."""
    unique_id = str(uuid.uuid4())[:8]
    username = f"golduser_{unique_id}"
    discord_id = random.randint(100000000000000000, 999999999999999999)

    user = await User.objects.acreate(
        username=username,
        email=f"gold_{unique_id}@test.com",
    )

    await UserGroups.objects.acreate(
        user=user,
        authentik_id=f"test-gold-uid-{unique_id}",
        groups=["WCComps_GoldTeam"],
    )

    await DiscordLink.objects.acreate(
        user=user,
        discord_id=discord_id,
        discord_username=username,
        is_active=True,
    )

    user._discord_id = discord_id
    return user


@pytest_asyncio.fixture
async def blue_team_user(db) -> User:
    """Create a user with Blue Team permissions (no orange access)."""
    unique_id = str(uuid.uuid4())[:8]
    username = f"blueuser_{unique_id}"
    discord_id = random.randint(100000000000000000, 999999999999999999)

    user = await User.objects.acreate(
        username=username,
        email=f"blue_{unique_id}@test.com",
    )

    await UserGroups.objects.acreate(
        user=user,
        authentik_id=f"test-blue-uid-{unique_id}",
        groups=["WCComps_BlueTeam01"],
    )

    await DiscordLink.objects.acreate(
        user=user,
        discord_id=discord_id,
        discord_username=username,
        is_active=True,
    )

    user._discord_id = discord_id
    return user


@pytest_asyncio.fixture
async def test_team(db) -> Team:
    """Create a test team."""
    unique_id = str(uuid.uuid4())[:8]
    team_number = random.randint(1, 50)
    return await Team.objects.acreate(
        team_number=team_number,
        team_name=f"Test Team {unique_id}",
        is_active=True,
    )


@pytest.fixture
def mock_interaction():
    """Create a mock Discord interaction."""
    interaction = AsyncMock(spec=discord.Interaction)
    interaction.user = MagicMock(spec=discord.User)
    interaction.user.id = 123456789
    interaction.user.name = "testuser"
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()
    return interaction


@pytest.fixture
def cog():
    """Create an OrangeTeamCog instance."""
    bot = MagicMock()
    return OrangeTeamCog(bot)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestOrangeSubmit:
    """Tests for /orange submit command."""

    async def test_submit_success(self, cog, mock_interaction, orange_team_user, test_team):
        """Orange team user can submit adjustment."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_submit.callback(
            cog,
            mock_interaction,
            team_number=test_team.team_number,
            points="15.5",
            description="Good customer service",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "embed" in call_args[1]
        assert call_args[1]["ephemeral"] is True

        bonus = await OrangeTeamScore.objects.filter(team=test_team).afirst()
        assert bonus is not None
        assert bonus.points_awarded == Decimal("15.5")
        assert bonus.description == "Good customer service"

    async def test_submit_invalid_team_range(self, cog, mock_interaction, orange_team_user):
        """Team number outside valid range is rejected."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_submit.callback(
            cog,
            mock_interaction,
            team_number=999,
            points="10",
            description="Test",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "between 1 and 50" in call_args[0][0]

    async def test_submit_nonexistent_team(self, cog, mock_interaction, orange_team_user):
        """Non-existent team number in valid range is rejected."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_submit.callback(
            cog,
            mock_interaction,
            team_number=49,
            points="10",
            description="Test",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "not found" in call_args[0][0]

    async def test_submit_invalid_points(self, cog, mock_interaction, orange_team_user, test_team):
        """Invalid points value is rejected."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_submit.callback(
            cog,
            mock_interaction,
            team_number=test_team.team_number,
            points="not-a-number",
            description="Test",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "Invalid points" in call_args[0][0]

    async def test_gold_team_can_submit(self, cog, mock_interaction, gold_team_user, test_team):
        """Gold team user can also submit adjustments."""
        mock_interaction.user.id = gold_team_user._discord_id

        await cog.orange_submit.callback(
            cog,
            mock_interaction,
            team_number=test_team.team_number,
            points="5",
            description="Gold team adjustment",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "embed" in call_args[1]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestOrangeList:
    """Tests for /orange list command."""

    async def test_list_empty(self, cog, mock_interaction, orange_team_user):
        """Empty list returns appropriate message."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_list.callback(cog, mock_interaction, status="pending")

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "No pending adjustments" in call_args[0][0]

    async def test_list_with_adjustments(self, cog, mock_interaction, orange_team_user, test_team):
        """List shows existing adjustments."""
        mock_interaction.user.id = orange_team_user._discord_id

        await OrangeTeamScore.objects.acreate(
            team=test_team,
            description="Test bonus",
            points_awarded=Decimal("25.00"),
            is_approved=False,
        )

        await cog.orange_list.callback(cog, mock_interaction, status="pending")

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "embed" in call_args[1]
