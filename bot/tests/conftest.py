"""Pytest fixtures for bot command testing."""

from typing import Any
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
import discord
from django.contrib.auth.models import User
from allauth.socialaccount.models import SocialAccount
from core.models import Team, DiscordLink


@pytest.fixture
def mock_interaction() -> Any:
    """Create a mock Discord interaction."""
    interaction = AsyncMock(spec=discord.Interaction)

    # Mock user
    interaction.user = MagicMock(spec=discord.User)
    interaction.user.id = 211533935144992768
    interaction.user.name = "testuser"
    interaction.user.mention = "<@211533935144992768>"

    # Mock guild
    interaction.guild = MagicMock(spec=discord.Guild)
    interaction.guild.id = 525435725123158026
    interaction.guild.name = "Test Guild"

    # Mock response
    interaction.response = AsyncMock()
    interaction.followup = AsyncMock()

    return interaction


@pytest_asyncio.fixture
async def mock_admin_user(db: Any) -> User:
    import uuid
    import random

    unique_id = str(uuid.uuid4())[:8]
    username = f"testadmin_{unique_id}"
    discord_id = random.randint(100000000000000000, 999999999999999999)

    user = await User.objects.acreate(
        username=username,
        email=f"admin_{unique_id}@test.com",
    )

    await SocialAccount.objects.acreate(
        user=user,
        provider="authentik",
        uid=f"test-uid-{unique_id}",
        extra_data={
            "id_token": {
                "groups": [
                    "WCComps_Discord_Admin",
                    "WCComps_Ticketing_Admin",
                ],
                "preferred_username": username,
            }
        },
    )

    await DiscordLink.objects.acreate(
        discord_id=discord_id,
        authentik_username=username,
        is_active=True,
        team=None,
    )

    user._discord_id = discord_id
    return user


@pytest_asyncio.fixture
async def mock_team_user(db: Any) -> User:
    import uuid
    import random

    unique_id = str(uuid.uuid4())[:8]
    username = f"teammember_{unique_id}"
    discord_id = random.randint(100000000000000000, 999999999999999999)

    user = await User.objects.acreate(
        username=username,
        email=f"team_{unique_id}@test.com",
    )

    team = await Team.objects.acreate(
        team_number=int(unique_id, 16) % 10000,
        team_name=f"Test Team {unique_id}",
        max_members=5,
    )

    await SocialAccount.objects.acreate(
        user=user,
        provider="authentik",
        uid=f"test-team-uid-{unique_id}",
        extra_data={
            "id_token": {
                "groups": ["WCComps_BlueTeam01"],
                "preferred_username": username,
            }
        },
    )

    await DiscordLink.objects.acreate(
        discord_id=discord_id,
        authentik_username=username,
        is_active=True,
        team=team,
    )

    user._discord_id = discord_id
    return user


@pytest.fixture
def mock_bot() -> Any:
    """Create a mock Discord bot."""
    bot = AsyncMock(spec=discord.Client)
    bot.user = MagicMock()
    bot.user.id = 1422808875651829785
    bot.user.name = "wccomps-bot"
    return bot


@pytest.fixture
def mock_discord_guild() -> Any:
    guild = MagicMock(spec=discord.Guild)
    guild.id = 525435725123158026
    guild.name = "Test Guild"

    member1 = MagicMock(spec=discord.Member)
    member1.id = 111111111
    member1.name = "member1"
    member1.roles = []

    member2 = MagicMock(spec=discord.Member)
    member2.id = 222222222
    member2.name = "member2"
    member2.roles = []

    team1_role = MagicMock(spec=discord.Role)
    team1_role.id = 5001
    team1_role.name = "Team 01"
    team1_role.members = [member1]

    team2_role = MagicMock(spec=discord.Role)
    team2_role.id = 5002
    team2_role.name = "Team 02"
    team2_role.members = [member2]

    blueteam_role = MagicMock(spec=discord.Role)
    blueteam_role.id = 525444104763736075
    blueteam_role.name = "Blueteam"
    blueteam_role.members = [member1, member2]

    member1.roles = [team1_role, blueteam_role]
    member2.roles = [team2_role, blueteam_role]

    def get_role_by_id(role_id: int) -> Any:
        role_map = {
            5001: team1_role,
            5002: team2_role,
            525444104763736075: blueteam_role,
        }
        return role_map.get(role_id)

    guild.get_role = MagicMock(side_effect=get_role_by_id)
    guild.roles = [team1_role, team2_role, blueteam_role]

    member1.remove_roles = AsyncMock()
    member2.remove_roles = AsyncMock()

    return guild


def pytest_configure(config):  # type: ignore
    """Configure pytest to use database flushing for isolation between tests."""
    config.addinivalue_line(
        "markers",
        "django_db(transaction=True): Enable database flushing for test isolation",
    )


@pytest.fixture(scope="function")
def db(transactional_db):  # type: ignore
    """
    Override the default db fixture to use transactional_db instead.

    This forces all tests to use TransactionTestCase behavior (database flushing)
    instead of TestCase behavior (transaction rollback), providing stronger
    test isolation.
    """
    return transactional_db


@pytest.fixture(autouse=True)
def setup_django() -> None:
    """Set up Django for tests."""
    import os
    import django

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wccomps.settings")
    django.setup()
