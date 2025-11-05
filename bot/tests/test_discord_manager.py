"""Tests for Discord manager functionality."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock
import discord
from core.models import Team
from bot.discord_manager import DiscordManager


@pytest_asyncio.fixture
async def team(db):
    """Create a test team with unique team number."""
    import random

    team_num = random.randint(100, 9999)
    return await Team.objects.acreate(
        team_number=team_num,
        team_name=f"Test Team {team_num}",
        authentik_group=f"WCComps_Team{team_num:02d}",
    )


@pytest.fixture
def mock_guild_with_base_roles():
    """Create a mock Discord guild with base role setup."""
    guild = MagicMock(spec=discord.Guild)
    guild.id = 525435725123158026
    guild.name = "Test Guild"

    # Create base roles that might be referenced
    white_team_role = MagicMock(spec=discord.Role)
    white_team_role.name = "White Team"
    white_team_role.id = 5001

    observers_role = MagicMock(spec=discord.Role)
    observers_role.name = "WRCCDC Observers"
    observers_role.id = 5002

    orange_team_role = MagicMock(spec=discord.Role)
    orange_team_role.name = "Orange Team"
    orange_team_role.id = 5003

    room_judge_role = MagicMock(spec=discord.Role)
    room_judge_role.name = "WRCCDC Room Judge"
    room_judge_role.id = 5004

    ops_team_role = MagicMock(spec=discord.Role)
    ops_team_role.name = "WRCCDC Operations Team"
    ops_team_role.id = 5005

    server_owners_role = MagicMock(spec=discord.Role)
    server_owners_role.name = "WRCCDC Server Owners"
    server_owners_role.id = 5006

    team_01_role = MagicMock(spec=discord.Role)
    team_01_role.name = "Team 01"
    team_01_role.color = discord.Color.blue()
    team_01_role.position = 10
    team_01_role.id = 5010

    # Create default role (@everyone)
    default_role = MagicMock(spec=discord.Role)
    default_role.name = "@everyone"
    default_role.id = 525435725123158026  # Same as guild ID
    guild.default_role = default_role

    guild.roles = [
        default_role,
        white_team_role,
        observers_role,
        orange_team_role,
        room_judge_role,
        ops_team_role,
        server_owners_role,
        team_01_role,
    ]
    guild.categories = []

    # Setup get_role method with dynamic lookup
    def get_role_by_id(role_id):
        for role in guild.roles:
            if role.id == role_id:
                return role
        return None

    guild.get_role = MagicMock(side_effect=get_role_by_id)

    # Setup create_role method with counter to avoid ID collisions
    role_counter = {"count": len(guild.roles)}

    async def create_role(**kwargs):
        role = MagicMock(spec=discord.Role)
        role.name = kwargs.get("name", "New Role")
        role.color = kwargs.get("color", discord.Color.default())
        role.id = 6000 + role_counter["count"]
        role.position = len(guild.roles)
        role.edit = AsyncMock()
        guild.roles.append(role)
        role_counter["count"] += 1
        return role

    guild.create_role = AsyncMock(side_effect=create_role)

    # Setup create_category method with counter to avoid ID collisions
    category_counter = {"count": 0}

    async def create_category(**kwargs):
        category = MagicMock(spec=discord.CategoryChannel)
        category.name = kwargs.get("name", "New Category")
        category.id = 7000 + category_counter["count"]
        category.position = len(guild.categories)
        category.edit = AsyncMock()

        # Mock create_text_channel
        async def create_text_channel(name, **ch_kwargs):
            channel = MagicMock(spec=discord.TextChannel)
            channel.name = name
            channel.id = 8000 + category_counter["count"]
            return channel

        # Mock create_voice_channel
        async def create_voice_channel(name, **ch_kwargs):
            channel = MagicMock(spec=discord.VoiceChannel)
            channel.name = name
            channel.id = 9000 + category_counter["count"]
            return channel

        category.create_text_channel = AsyncMock(side_effect=create_text_channel)
        category.create_voice_channel = AsyncMock(side_effect=create_voice_channel)

        guild.categories.append(category)
        category_counter["count"] += 1
        return category

    guild.create_category = AsyncMock(side_effect=create_category)

    return guild


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestSetupTeamInfrastructure:
    """Test setup_team_infrastructure method."""

    async def test_creates_role_with_correct_name(
        self, team, mock_guild_with_base_roles
    ):
        """Test that a role is created with format 'Team XX'."""
        manager = DiscordManager(mock_guild_with_base_roles)

        role, category = await manager.setup_team_infrastructure(team.team_number)

        assert role is not None
        assert role.name == f"Team {team.team_number:02d}"

    async def test_creates_category_with_correct_name(
        self, team, mock_guild_with_base_roles
    ):
        """Test that a category is created with format 'team XX'."""
        manager = DiscordManager(mock_guild_with_base_roles)

        role, category = await manager.setup_team_infrastructure(team.team_number)

        assert category is not None
        assert category.name == f"team {team.team_number:02d}"

    async def test_creates_channels_within_category(
        self, team, mock_guild_with_base_roles
    ):
        """Test that text and voice channels are created."""
        manager = DiscordManager(mock_guild_with_base_roles)

        role, category = await manager.setup_team_infrastructure(team.team_number)

        # Verify create_text_channel was called with correct name
        category.create_text_channel.assert_called()
        call_args = category.create_text_channel.call_args
        expected_text = f"team{team.team_number:02d}-chat"
        assert expected_text in call_args[0] or call_args[0][0] == expected_text

        # Verify create_voice_channel was called with correct name
        category.create_voice_channel.assert_called()
        call_args = category.create_voice_channel.call_args
        expected_voice = f"team{team.team_number:02d}-voice"
        assert expected_voice in call_args[0] or call_args[0][0] == expected_voice

    async def test_returns_none_when_team_not_found(self, mock_guild_with_base_roles):
        """Test that method returns None when team doesn't exist."""
        guild = mock_guild_with_base_roles
        manager = DiscordManager(guild)

        # Track that guild methods are NOT called for non-existent team
        initial_role_count = len(guild.roles)
        initial_category_count = len(guild.categories)

        role, category = await manager.setup_team_infrastructure(999)

        assert role is None
        assert category is None
        # Verify no resources were created
        assert len(guild.roles) == initial_role_count
        assert len(guild.categories) == initial_category_count
        # Verify create_role was never called
        guild.create_role.assert_not_called()

    async def test_returns_tuple(self, team, mock_guild_with_base_roles):
        """Test that method returns a tuple of (role, category)."""
        manager = DiscordManager(mock_guild_with_base_roles)

        result = await manager.setup_team_infrastructure(team.team_number)

        assert isinstance(result, tuple)
        assert len(result) == 2

    async def test_idempotent_no_duplicates_created(
        self, team, mock_guild_with_base_roles
    ):
        """Test that running setup twice does not create duplicate roles or categories."""
        manager = DiscordManager(mock_guild_with_base_roles)
        guild = mock_guild_with_base_roles

        # Track initial counts
        initial_role_count = len(guild.roles)
        initial_category_count = len(guild.categories)

        # First setup
        role1, category1 = await manager.setup_team_infrastructure(team.team_number)
        assert role1 is not None
        assert category1 is not None

        # Verify one role and one category were created
        assert len(guild.roles) == initial_role_count + 1
        assert len(guild.categories) == initial_category_count + 1

        # Second setup (should be idempotent)
        role2, category2 = await manager.setup_team_infrastructure(team.team_number)
        assert role2 is not None
        assert category2 is not None

        # Verify NO additional roles or categories were created
        assert len(guild.roles) == initial_role_count + 1
        assert len(guild.categories) == initial_category_count + 1

        # Verify same instances returned
        assert role2.id == role1.id
        assert category2.id == category1.id

    async def test_self_healing_recreates_missing_category(
        self, team, mock_guild_with_base_roles
    ):
        """Test self-healing: when category is deleted but role exists, category is recreated."""
        manager = DiscordManager(mock_guild_with_base_roles)
        guild = mock_guild_with_base_roles

        # First setup - create both role and category
        role1, category1 = await manager.setup_team_infrastructure(team.team_number)
        assert role1 is not None
        assert category1 is not None

        original_role_id = role1.id
        original_category_id = category1.id

        # Simulate category deletion (remove from guild.categories list)
        guild.categories.remove(category1)

        # Track role count before self-healing
        role_count_before = len(guild.roles)

        # Second setup - should detect missing category and recreate it
        role2, category2 = await manager.setup_team_infrastructure(team.team_number)

        # Verify role was NOT recreated (same role returned)
        assert role2.id == original_role_id
        assert len(guild.roles) == role_count_before

        # Verify category WAS recreated (new category created)
        assert category2 is not None
        assert category2.id != original_category_id

        # Verify database updated with new category ID
        await team.arefresh_from_db()
        assert team.discord_role_id == original_role_id
        assert team.discord_category_id == category2.id

    async def test_self_healing_recreates_missing_role(
        self, team, mock_guild_with_base_roles
    ):
        """Test self-healing: when role is deleted but category exists, role is recreated."""
        manager = DiscordManager(mock_guild_with_base_roles)
        guild = mock_guild_with_base_roles

        # First setup - create both role and category
        role1, category1 = await manager.setup_team_infrastructure(team.team_number)
        assert role1 is not None
        assert category1 is not None

        original_role_id = role1.id
        original_category_id = category1.id

        # Simulate role deletion (remove from guild.roles list)
        guild.roles.remove(role1)

        # Track category count before self-healing
        category_count_before = len(guild.categories)

        # Second setup - should detect missing role and recreate it
        role2, category2 = await manager.setup_team_infrastructure(team.team_number)

        # Verify category was NOT recreated (same category returned)
        assert category2.id == original_category_id
        assert len(guild.categories) == category_count_before

        # Verify role WAS recreated (new role created)
        assert role2 is not None
        assert role2.id != original_role_id

        # Verify database updated with new role ID
        await team.arefresh_from_db()
        assert team.discord_role_id == role2.id
        assert team.discord_category_id == original_category_id

    async def test_self_healing_recreates_both_if_both_deleted(
        self, team, mock_guild_with_base_roles
    ):
        """Test self-healing: when both role and category are deleted, both are recreated."""
        manager = DiscordManager(mock_guild_with_base_roles)
        guild = mock_guild_with_base_roles

        # First setup - create both role and category
        role1, category1 = await manager.setup_team_infrastructure(team.team_number)
        assert role1 is not None
        assert category1 is not None

        original_role_id = role1.id
        original_category_id = category1.id

        # Simulate both being deleted
        guild.roles.remove(role1)
        guild.categories.remove(category1)

        # Track counts before self-healing
        role_count_before = len(guild.roles)
        category_count_before = len(guild.categories)

        # Second setup - should detect both missing and recreate both
        role2, category2 = await manager.setup_team_infrastructure(team.team_number)

        # Verify both were recreated
        assert role2 is not None
        assert category2 is not None
        assert role2.id != original_role_id
        assert category2.id != original_category_id

        # Verify counts increased by 1 each
        assert len(guild.roles) == role_count_before + 1
        assert len(guild.categories) == category_count_before + 1

        # Verify database updated with new IDs
        await team.arefresh_from_db()
        assert team.discord_role_id == role2.id
        assert team.discord_category_id == category2.id


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestAssignTeamRole:
    """Test assign_team_role method."""

    async def test_assigns_team_role_successfully(
        self, team, mock_guild_with_base_roles
    ):
        """Test successfully assigning team role to a member."""
        guild = mock_guild_with_base_roles
        manager = DiscordManager(guild)

        # Setup team infrastructure first
        role, _ = await manager.setup_team_infrastructure(team.team_number)
        assert role is not None

        # Refresh team from database to get updated role ID
        await team.arefresh_from_db()

        # Create mock member
        member = MagicMock(spec=discord.Member)
        member.add_roles = AsyncMock()

        # Test assignment
        result = await manager.assign_team_role(member, team.team_number)

        assert result is True
        # Verify the exact role and reason were passed
        member.add_roles.assert_called_once_with(role, reason="WCComps team assignment")

    async def test_assigns_team_role_and_blueteam(
        self, team, mock_guild_with_base_roles
    ):
        """Test that both team role and Blueteam role are assigned."""
        guild = mock_guild_with_base_roles
        manager = DiscordManager(guild)

        # Setup team infrastructure
        role, _ = await manager.setup_team_infrastructure(team.team_number)

        # Add Blueteam role to guild
        blueteam_role = MagicMock(spec=discord.Role)
        blueteam_role.name = "Blueteam"
        blueteam_role.id = 9001
        guild.roles.append(blueteam_role)

        member = MagicMock(spec=discord.Member)
        member.add_roles = AsyncMock()

        result = await manager.assign_team_role(member, team.team_number)

        assert result is True
        # Verify both roles were assigned
        call_args = member.add_roles.call_args[0]
        assert len(call_args) == 2
        assert role in call_args
        assert blueteam_role in call_args

    async def test_assign_team_role_team_not_found(self, mock_guild_with_base_roles):
        """Test assigning role when team doesn't exist."""
        manager = DiscordManager(mock_guild_with_base_roles)
        member = MagicMock(spec=discord.Member)
        member.add_roles = AsyncMock()

        result = await manager.assign_team_role(member, 999)

        assert result is False
        member.add_roles.assert_not_called()

    async def test_assign_team_role_no_discord_role_id(
        self, team, mock_guild_with_base_roles
    ):
        """Test assigning role when team has no discord_role_id."""
        manager = DiscordManager(mock_guild_with_base_roles)
        member = MagicMock(spec=discord.Member)
        member.add_roles = AsyncMock()

        # Don't setup infrastructure, so team has no role ID
        result = await manager.assign_team_role(member, team.team_number)

        assert result is False
        member.add_roles.assert_not_called()

    async def test_assign_team_role_role_not_found_in_guild(
        self, team, mock_guild_with_base_roles
    ):
        """Test assigning role when Discord role doesn't exist in guild."""
        manager = DiscordManager(mock_guild_with_base_roles)
        member = MagicMock(spec=discord.Member)
        member.add_roles = AsyncMock()

        # Set role ID that doesn't exist in guild
        team.discord_role_id = 99999
        await team.asave()

        result = await manager.assign_team_role(member, team.team_number)

        assert result is False
        member.add_roles.assert_not_called()

    async def test_assign_team_role_permission_denied(
        self, team, mock_guild_with_base_roles
    ):
        """Test handling Forbidden error when assigning role."""
        guild = mock_guild_with_base_roles
        manager = DiscordManager(guild)

        # Setup team infrastructure
        role, _ = await manager.setup_team_infrastructure(team.team_number)

        member = MagicMock(spec=discord.Member)
        member.add_roles = AsyncMock(
            side_effect=discord.errors.Forbidden(MagicMock(), "")
        )

        result = await manager.assign_team_role(member, team.team_number)

        assert result is False
        # Verify add_roles was called but raised Forbidden
        member.add_roles.assert_called_once_with(role, reason="WCComps team assignment")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestRemoveTeamRole:
    """Test remove_team_role method."""

    async def test_removes_team_role_successfully(
        self, team, mock_guild_with_base_roles
    ):
        """Test successfully removing team role from a member."""
        guild = mock_guild_with_base_roles
        manager = DiscordManager(guild)

        # Setup team infrastructure
        role, _ = await manager.setup_team_infrastructure(team.team_number)

        member = MagicMock(spec=discord.Member)
        member.roles = [role]
        member.remove_roles = AsyncMock()

        result = await manager.remove_team_role(member, team.team_number)

        assert result is True
        # Verify the exact role and reason were passed
        member.remove_roles.assert_called_once_with(role, reason="WCComps team removal")

    async def test_removes_team_role_and_blueteam(
        self, team, mock_guild_with_base_roles
    ):
        """Test that both team role and Blueteam role are removed."""
        guild = mock_guild_with_base_roles
        manager = DiscordManager(guild)

        # Setup team infrastructure
        role, _ = await manager.setup_team_infrastructure(team.team_number)

        # Add Blueteam role
        blueteam_role = MagicMock(spec=discord.Role)
        blueteam_role.name = "Blueteam"
        blueteam_role.id = 9001
        guild.roles.append(blueteam_role)

        member = MagicMock(spec=discord.Member)
        member.roles = [role, blueteam_role]
        member.remove_roles = AsyncMock()

        result = await manager.remove_team_role(member, team.team_number)

        assert result is True
        # Verify both roles were removed
        call_args = member.remove_roles.call_args[0]
        assert len(call_args) == 2
        assert role in call_args
        assert blueteam_role in call_args

    async def test_remove_team_role_team_not_found(self, mock_guild_with_base_roles):
        """Test removing role when team doesn't exist."""
        manager = DiscordManager(mock_guild_with_base_roles)
        member = MagicMock(spec=discord.Member)
        member.remove_roles = AsyncMock()

        result = await manager.remove_team_role(member, 999)

        assert result is False
        # Verify no roles were removed
        member.remove_roles.assert_not_called()

    async def test_remove_team_role_no_discord_role_id(
        self, team, mock_guild_with_base_roles
    ):
        """Test removing role when team has no discord_role_id."""
        manager = DiscordManager(mock_guild_with_base_roles)
        member = MagicMock(spec=discord.Member)
        member.remove_roles = AsyncMock()

        result = await manager.remove_team_role(member, team.team_number)

        assert result is False
        # Verify no roles were removed
        member.remove_roles.assert_not_called()

    async def test_remove_team_role_permission_denied(
        self, team, mock_guild_with_base_roles
    ):
        """Test handling Forbidden error when removing role."""
        guild = mock_guild_with_base_roles
        manager = DiscordManager(guild)

        # Setup team infrastructure
        role, _ = await manager.setup_team_infrastructure(team.team_number)

        member = MagicMock(spec=discord.Member)
        member.roles = [role]
        member.remove_roles = AsyncMock(
            side_effect=discord.errors.Forbidden(MagicMock(), "")
        )

        result = await manager.remove_team_role(member, team.team_number)

        assert result is False
        # Verify remove_roles was called but raised Forbidden
        member.remove_roles.assert_called_once_with(role, reason="WCComps team removal")


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestRemoveAllTeamRoles:
    """Test remove_all_team_roles method."""

    async def test_removes_all_team_roles(self, mock_guild_with_base_roles):
        """Test removing all team roles from all members."""
        guild = mock_guild_with_base_roles
        manager = DiscordManager(guild)

        # Create multiple teams
        team1 = await Team.objects.acreate(
            team_number=501, team_name="Team A", max_members=5
        )
        team2 = await Team.objects.acreate(
            team_number=502, team_name="Team B", max_members=5
        )

        # Setup infrastructure for both teams
        role1, _ = await manager.setup_team_infrastructure(team1.team_number)
        role2, _ = await manager.setup_team_infrastructure(team2.team_number)

        # Create mock members
        member1 = MagicMock(spec=discord.Member)
        member1.remove_roles = AsyncMock()
        member2 = MagicMock(spec=discord.Member)
        member2.remove_roles = AsyncMock()

        # Assign members to roles
        role1.members = [member1]
        role2.members = [member2]

        result = await manager.remove_all_team_roles()

        # Verify roles were removed with correct arguments
        assert result == 2
        member1.remove_roles.assert_called_once_with(role1, reason="Competition ended")
        member2.remove_roles.assert_called_once_with(role2, reason="Competition ended")

    async def test_removes_blueteam_role(self, mock_guild_with_base_roles):
        """Test that Blueteam role is removed from all members."""
        guild = mock_guild_with_base_roles
        manager = DiscordManager(guild)

        # Create team
        team = await Team.objects.acreate(
            team_number=503, team_name="Team C", max_members=5
        )
        role, _ = await manager.setup_team_infrastructure(team.team_number)

        # Add Blueteam role
        blueteam_role = MagicMock(spec=discord.Role)
        blueteam_role.name = "Blueteam"
        blueteam_role.id = 9001

        member = MagicMock(spec=discord.Member)
        member.remove_roles = AsyncMock()
        member.roles = [role, blueteam_role]

        role.members = [member]
        blueteam_role.members = [member]
        guild.roles.append(blueteam_role)

        result = await manager.remove_all_team_roles()

        # Verify both team role and Blueteam were removed
        assert result == 1
        assert member.remove_roles.call_count == 2
        # First call removes both team role and Blueteam
        assert member.remove_roles.call_args_list[0] == (
            (role, blueteam_role),
            {"reason": "Competition ended"},
        )
        # Second call removes Blueteam from remaining members
        assert member.remove_roles.call_args_list[1] == (
            (blueteam_role,),
            {"reason": "Competition ended"},
        )

    async def test_handles_permission_errors(self, mock_guild_with_base_roles):
        """Test handling permission errors when removing roles."""
        guild = mock_guild_with_base_roles
        manager = DiscordManager(guild)

        # Create team
        team = await Team.objects.acreate(
            team_number=504, team_name="Team D", max_members=5
        )
        role, _ = await manager.setup_team_infrastructure(team.team_number)

        # Create member that raises Forbidden error
        member = MagicMock(spec=discord.Member)
        member.remove_roles = AsyncMock(
            side_effect=discord.errors.Forbidden(MagicMock(), "")
        )

        role.members = [member]

        # Should not raise exception, just log error
        result = await manager.remove_all_team_roles()

        # Count is 0 because the operation failed
        assert result == 0
