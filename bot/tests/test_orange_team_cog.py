"""Tests for Orange Team cog commands."""

import random
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
import pytest_asyncio
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import User
from scoring.models import OrangeCheckType, OrangeTeamBonus

from bot.cogs.orange_team import OrangeTeamCog
from person.models import Person
from team.models import Team


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

    await SocialAccount.objects.acreate(
        user=user,
        provider="authentik",
        uid=f"test-orange-uid-{unique_id}",
        extra_data={
            "id_token": {
                "groups": ["WCComps_OrangeTeam"],
                "preferred_username": username,
            }
        },
    )

    person = await Person.objects.aget(user=user)
    person.discord_id = discord_id
    person.authentik_groups = ["WCComps_OrangeTeam"]
    await person.asave()

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

    await SocialAccount.objects.acreate(
        user=user,
        provider="authentik",
        uid=f"test-gold-uid-{unique_id}",
        extra_data={
            "id_token": {
                "groups": ["WCComps_GoldTeam"],
                "preferred_username": username,
            }
        },
    )

    person = await Person.objects.aget(user=user)
    person.discord_id = discord_id
    person.authentik_groups = ["WCComps_GoldTeam"]
    await person.asave()

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

    await SocialAccount.objects.acreate(
        user=user,
        provider="authentik",
        uid=f"test-blue-uid-{unique_id}",
        extra_data={
            "id_token": {
                "groups": ["WCComps_BlueTeam01"],
                "preferred_username": username,
            }
        },
    )

    person = await Person.objects.aget(user=user)
    person.discord_id = discord_id
    person.authentik_groups = ["WCComps_BlueTeam01"]
    await person.asave()

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


@pytest_asyncio.fixture
async def check_type(db) -> OrangeCheckType:
    """Create a test check type."""
    unique_id = str(uuid.uuid4())[:8]
    return await OrangeCheckType.objects.acreate(
        name=f"Test Check {unique_id}",
        default_points=Decimal("10.00"),
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

    async def test_submit_requires_orange_team(self, cog, mock_interaction, blue_team_user, test_team, check_type):
        """Non-orange team users cannot submit adjustments."""
        mock_interaction.user.id = blue_team_user._discord_id

        await cog.orange_submit.callback(
            cog,
            mock_interaction,
            team_number=test_team.team_number,
            points="10",
            check_type=check_type.name,
            description="Test adjustment",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "Orange Team members only" in call_args[0][0]
        assert call_args[1]["ephemeral"] is True

    async def test_submit_success(self, cog, mock_interaction, orange_team_user, test_team, check_type):
        """Orange team user can submit adjustment."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_submit.callback(
            cog,
            mock_interaction,
            team_number=test_team.team_number,
            points="15.5",
            check_type=check_type.name,
            description="Good customer service",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "embed" in call_args[1]
        assert call_args[1]["ephemeral"] is True

        bonus = await OrangeTeamBonus.objects.filter(team=test_team).afirst()
        assert bonus is not None
        assert bonus.points_awarded == Decimal("15.5")
        assert bonus.description == "Good customer service"

    async def test_submit_invalid_team_range(self, cog, mock_interaction, orange_team_user, check_type):
        """Team number outside valid range is rejected."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_submit.callback(
            cog,
            mock_interaction,
            team_number=999,
            points="10",
            check_type=check_type.name,
            description="Test",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "between 1 and 50" in call_args[0][0]

    async def test_submit_nonexistent_team(self, cog, mock_interaction, orange_team_user, check_type):
        """Non-existent team number in valid range is rejected."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_submit.callback(
            cog,
            mock_interaction,
            team_number=49,
            points="10",
            check_type=check_type.name,
            description="Test",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "not found" in call_args[0][0]

    async def test_submit_invalid_check_type(self, cog, mock_interaction, orange_team_user, test_team):
        """Invalid check type is rejected."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_submit.callback(
            cog,
            mock_interaction,
            team_number=test_team.team_number,
            points="10",
            check_type="NonExistentCheckType",
            description="Test",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "not found" in call_args[0][0]

    async def test_submit_invalid_points(self, cog, mock_interaction, orange_team_user, test_team, check_type):
        """Invalid points value is rejected."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_submit.callback(
            cog,
            mock_interaction,
            team_number=test_team.team_number,
            points="not-a-number",
            check_type=check_type.name,
            description="Test",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "Invalid points" in call_args[0][0]

    async def test_gold_team_can_submit(self, cog, mock_interaction, gold_team_user, test_team, check_type):
        """Gold team user can also submit adjustments."""
        mock_interaction.user.id = gold_team_user._discord_id

        await cog.orange_submit.callback(
            cog,
            mock_interaction,
            team_number=test_team.team_number,
            points="5",
            check_type=check_type.name,
            description="Gold team adjustment",
        )

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "embed" in call_args[1]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestOrangeList:
    """Tests for /orange list command."""

    async def test_list_requires_orange_team(self, cog, mock_interaction, blue_team_user):
        """Non-orange team users cannot list adjustments."""
        mock_interaction.user.id = blue_team_user._discord_id

        await cog.orange_list.callback(cog, mock_interaction, status="pending")

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "Orange Team members only" in call_args[0][0]

    async def test_list_empty(self, cog, mock_interaction, orange_team_user):
        """Empty list returns appropriate message."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_list.callback(cog, mock_interaction, status="pending")

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "No pending adjustments" in call_args[0][0]

    async def test_list_with_adjustments(self, cog, mock_interaction, orange_team_user, test_team, check_type):
        """List shows existing adjustments."""
        mock_interaction.user.id = orange_team_user._discord_id

        await OrangeTeamBonus.objects.acreate(
            team=test_team,
            check_type=check_type,
            description="Test bonus",
            points_awarded=Decimal("25.00"),
            is_approved=False,
        )

        await cog.orange_list.callback(cog, mock_interaction, status="pending")

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "embed" in call_args[1]


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestOrangeCheckTypes:
    """Tests for /orange list-types, add-type, remove-type commands."""

    async def test_list_types_empty(self, cog, mock_interaction, orange_team_user):
        """Empty check types list returns appropriate message."""
        mock_interaction.user.id = orange_team_user._discord_id

        await OrangeCheckType.objects.all().adelete()

        await cog.orange_list_types.callback(cog, mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "No check types defined" in call_args[0][0]

    async def test_list_types_with_types(self, cog, mock_interaction, orange_team_user, check_type):
        """List shows existing check types."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_list_types.callback(cog, mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "embed" in call_args[1]

    async def test_add_type_success(self, cog, mock_interaction, orange_team_user):
        """Orange team can add new check type."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_add_type.callback(cog, mock_interaction, name="New Check", default_points="15")

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "Created check type" in call_args[0][0]

        check = await OrangeCheckType.objects.filter(name="New Check").afirst()
        assert check is not None
        assert check.default_points == Decimal("15")

    async def test_add_type_duplicate(self, cog, mock_interaction, orange_team_user, check_type):
        """Cannot add duplicate check type."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_add_type.callback(cog, mock_interaction, name=check_type.name, default_points="10")

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "already exists" in call_args[0][0]

    async def test_remove_type_success(self, cog, mock_interaction, orange_team_user, check_type):
        """Orange team can remove check type."""
        mock_interaction.user.id = orange_team_user._discord_id
        name = check_type.name

        await cog.orange_remove_type.callback(cog, mock_interaction, name=name)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "Removed check type" in call_args[0][0]

        check = await OrangeCheckType.objects.filter(name=name).afirst()
        assert check is None

    async def test_remove_type_not_found(self, cog, mock_interaction, orange_team_user):
        """Cannot remove non-existent check type."""
        mock_interaction.user.id = orange_team_user._discord_id

        await cog.orange_remove_type.callback(cog, mock_interaction, name="NonExistent")

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "not found" in call_args[0][0]
