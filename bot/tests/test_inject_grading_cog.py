"""Tests for Inject Grading cog commands."""

import random
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
import pytest_asyncio
from django.contrib.auth.models import User
from scoring.models import InjectGrade

from bot.cogs.inject_grading import InjectGradingCog
from core.models import UserGroups
from team.models import DiscordLink, Team


@pytest_asyncio.fixture
async def white_team_user(db) -> User:
    """Create a user with White Team permissions."""
    unique_id = str(uuid.uuid4())[:8]
    username = f"whiteuser_{unique_id}"
    discord_id = random.randint(100000000000000000, 999999999999999999)

    user = await User.objects.acreate(
        username=username,
        email=f"white_{unique_id}@test.com",
    )

    await UserGroups.objects.acreate(
        user=user,
        authentik_id=f"test-white-uid-{unique_id}",
        groups=["WCComps_WhiteTeam"],
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
    """Create a user with Blue Team permissions (no inject grading access)."""
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
    """Create an InjectGradingCog instance."""
    bot = MagicMock()
    return InjectGradingCog(bot)


@pytest.fixture
def mock_quotient_injects():
    """Mock inject data from Quotient."""

    class MockInject:
        def __init__(self, inject_id, title):
            self.inject_id = inject_id
            self.title = title

    return [
        MockInject("INJ-001", "Business Email Compromise"),
        MockInject("INJ-002", "Ransomware Response"),
        MockInject("INJ-003", "CEO Fraud Report"),
    ]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestInjectList:
    """Tests for /inject list command."""

    async def test_list_white_team_allowed(self, cog, mock_interaction, white_team_user, mock_quotient_injects):
        """White team user can list injects."""
        mock_interaction.user.id = white_team_user._discord_id

        with patch("quotient.client.QuotientClient") as mock_client:
            mock_client.return_value.get_injects.return_value = mock_quotient_injects
            await cog.inject_list.callback(cog, mock_interaction)

        mock_interaction.response.defer.assert_called_once()
        mock_interaction.followup.send.assert_called_once()
        call_args = mock_interaction.followup.send.call_args
        assert "embed" in call_args[1]

    async def test_list_gold_team_allowed(self, cog, mock_interaction, gold_team_user, mock_quotient_injects):
        """Gold team user can list injects."""
        mock_interaction.user.id = gold_team_user._discord_id

        with patch("quotient.client.QuotientClient") as mock_client:
            mock_client.return_value.get_injects.return_value = mock_quotient_injects
            await cog.inject_list.callback(cog, mock_interaction)

        mock_interaction.response.defer.assert_called_once()
        mock_interaction.followup.send.assert_called_once()

    async def test_list_empty(self, cog, mock_interaction, white_team_user):
        """Empty inject list returns appropriate message."""
        mock_interaction.user.id = white_team_user._discord_id

        with patch("quotient.client.QuotientClient") as mock_client:
            mock_client.return_value.get_injects.return_value = []
            await cog.inject_list.callback(cog, mock_interaction)

        mock_interaction.followup.send.assert_called_once()
        call_args = mock_interaction.followup.send.call_args
        assert "No injects available" in call_args[0][0]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestInjectGrade:
    """Tests for /inject grade command."""

    async def test_grade_invalid_team_range(self, cog, mock_interaction, white_team_user):
        """Team number outside valid range is rejected."""
        mock_interaction.user.id = white_team_user._discord_id

        await cog.inject_grade.callback(
            cog,
            mock_interaction,
            inject_id="INJ-001",
            team_number=999,
            points="100",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "between 1 and 50" in call_args[0][0]

    async def test_grade_invalid_points(self, cog, mock_interaction, white_team_user, test_team):
        """Invalid points value is rejected."""
        mock_interaction.user.id = white_team_user._discord_id

        await cog.inject_grade.callback(
            cog,
            mock_interaction,
            inject_id="INJ-001",
            team_number=test_team.team_number,
            points="not-a-number",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "Invalid points" in call_args[0][0]

    async def test_grade_negative_points(self, cog, mock_interaction, white_team_user, test_team):
        """Negative points are rejected."""
        mock_interaction.user.id = white_team_user._discord_id

        await cog.inject_grade.callback(
            cog,
            mock_interaction,
            inject_id="INJ-001",
            team_number=test_team.team_number,
            points="-50",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "cannot be negative" in call_args[0][0]

    async def test_grade_nonexistent_team(self, cog, mock_interaction, white_team_user):
        """Non-existent team in valid range is rejected."""
        mock_interaction.user.id = white_team_user._discord_id

        await cog.inject_grade.callback(
            cog,
            mock_interaction,
            inject_id="INJ-001",
            team_number=49,
            points="100",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "not found" in call_args[0][0]

    async def test_grade_success(self, cog, mock_interaction, white_team_user, test_team, mock_quotient_injects):
        """White team user can grade inject."""
        mock_interaction.user.id = white_team_user._discord_id

        with patch("quotient.client.QuotientClient") as mock_client:
            mock_client.return_value.get_injects.return_value = mock_quotient_injects
            await cog.inject_grade.callback(
                cog,
                mock_interaction,
                inject_id="INJ-001",
                team_number=test_team.team_number,
                points="75.5",
                notes="Good response",
            )

        mock_interaction.response.defer.assert_called_once()
        mock_interaction.followup.send.assert_called_once()
        call_args = mock_interaction.followup.send.call_args
        assert "embed" in call_args[1]

        grade = await InjectGrade.objects.filter(team=test_team, inject_id="INJ-001").afirst()
        assert grade is not None
        assert grade.points_awarded == Decimal("75.5")
        assert grade.notes == "Good response"
        assert grade.is_approved is False


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestInjectListGrades:
    """Tests for /inject list-grades command."""

    async def test_list_grades_empty(self, cog, mock_interaction, white_team_user):
        """Empty grades list returns appropriate message."""
        mock_interaction.user.id = white_team_user._discord_id

        await cog.inject_list_grades.callback(cog, mock_interaction, status="pending")

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "No pending grades" in call_args[0][0]

    async def test_list_grades_with_grades(self, cog, mock_interaction, white_team_user, test_team):
        """List shows existing grades."""
        mock_interaction.user.id = white_team_user._discord_id

        await InjectGrade.objects.acreate(
            team=test_team,
            inject_id="INJ-001",
            inject_name="Test Inject",
            points_awarded=Decimal("100.00"),
            is_approved=False,
        )

        await cog.inject_list_grades.callback(cog, mock_interaction, status="pending")

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "embed" in call_args[1]

    async def test_list_grades_filter_by_inject(self, cog, mock_interaction, white_team_user, test_team):
        """Can filter grades by inject ID."""
        mock_interaction.user.id = white_team_user._discord_id

        await InjectGrade.objects.acreate(
            team=test_team,
            inject_id="INJ-001",
            inject_name="Test Inject 1",
            points_awarded=Decimal("100.00"),
            is_approved=False,
        )
        await InjectGrade.objects.acreate(
            team=test_team,
            inject_id="INJ-002",
            inject_name="Test Inject 2",
            points_awarded=Decimal("50.00"),
            is_approved=False,
        )

        await cog.inject_list_grades.callback(cog, mock_interaction, inject_id="INJ-001", status="pending")

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "embed" in call_args[1]
