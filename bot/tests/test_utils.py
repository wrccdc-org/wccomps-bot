"""Tests for utility functions."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
import discord
import pytest
from bot.utils import (
    format_team_name,
    format_role_name,
    format_category_name,
    safe_add_role,
    safe_remove_role,
    remove_blueteam_role,
    get_team_or_respond,
    get_team_member_discord_ids,
    log_to_ops_channel,
)
from core.models import Team, DiscordLink


class TestFormatting:
    """Test formatting utility functions."""

    def test_format_team_name_single_digit(self) -> None:
        """Test team name formatting for single digit teams."""
        assert format_team_name(1) == "BlueTeam01"
        assert format_team_name(5) == "BlueTeam05"
        assert format_team_name(9) == "BlueTeam09"

    def test_format_team_name_double_digit(self) -> None:
        """Test team name formatting for double digit teams."""
        assert format_team_name(10) == "BlueTeam10"
        assert format_team_name(25) == "BlueTeam25"
        assert format_team_name(50) == "BlueTeam50"

    def test_format_role_name_single_digit(self) -> None:
        """Test role name formatting for single digit teams."""
        assert format_role_name(1) == "Team 01"
        assert format_role_name(7) == "Team 07"

    def test_format_role_name_double_digit(self) -> None:
        """Test role name formatting for double digit teams."""
        assert format_role_name(15) == "Team 15"
        assert format_role_name(42) == "Team 42"

    def test_format_category_name(self) -> None:
        """Test category name formatting."""
        assert format_category_name(1) == "team 01"
        assert format_category_name(12) == "team 12"
        assert format_category_name(50) == "team 50"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestRoleManagement:
    """Test role add/remove utility functions."""

    async def test_safe_add_role_success(self) -> None:
        """Test successfully adding a role to a member."""
        member = MagicMock(spec=discord.Member)
        member.roles = []
        member.add_roles = AsyncMock()

        role = MagicMock(spec=discord.Role)
        role.name = "Test Role"

        result = await safe_add_role(member, role, reason="test")

        assert result is True
        member.add_roles.assert_called_once_with(role, reason="test")

    async def test_safe_add_role_already_has(self) -> None:
        """Test adding a role when member already has it."""
        role = MagicMock(spec=discord.Role)
        role.name = "Test Role"

        member = MagicMock(spec=discord.Member)
        member.roles = [role]
        member.add_roles = AsyncMock()

        result = await safe_add_role(member, role)

        assert result is True
        member.add_roles.assert_not_called()

    async def test_safe_add_role_permission_denied(self) -> None:
        """Test handling permission denied when adding role."""
        member = MagicMock(spec=discord.Member)
        member.roles = []
        member.add_roles = AsyncMock(
            side_effect=discord.errors.Forbidden(MagicMock(), "No permission")
        )

        role = MagicMock(spec=discord.Role)
        role.name = "Test Role"

        result = await safe_add_role(member, role)

        assert result is False

    async def test_safe_remove_role_success(self) -> None:
        """Test successfully removing a role from a member."""
        role = MagicMock(spec=discord.Role)
        role.name = "Test Role"

        member = MagicMock(spec=discord.Member)
        member.roles = [role]
        member.remove_roles = AsyncMock()

        result = await safe_remove_role(member, role, reason="test")

        assert result is True
        member.remove_roles.assert_called_once_with(role, reason="test")

    async def test_safe_remove_role_not_present(self) -> None:
        """Test removing a role when member doesn't have it."""
        role = MagicMock(spec=discord.Role)
        role.name = "Test Role"

        member = MagicMock(spec=discord.Member)
        member.roles = []
        member.remove_roles = AsyncMock()

        result = await safe_remove_role(member, role)

        assert result is True
        member.remove_roles.assert_not_called()

    async def test_safe_remove_role_permission_denied(self) -> None:
        """Test handling permission denied when removing role."""
        role = MagicMock(spec=discord.Role)
        role.name = "Test Role"

        member = MagicMock(spec=discord.Member)
        member.roles = [role]
        member.remove_roles = AsyncMock(
            side_effect=discord.errors.Forbidden(MagicMock(), "No permission")
        )

        result = await safe_remove_role(member, role)

        assert result is False

    async def test_remove_blueteam_role_success(self) -> None:
        """Test removing Blueteam role from member."""
        blueteam_role = MagicMock(spec=discord.Role)
        blueteam_role.name = "Blueteam"

        member = MagicMock(spec=discord.Member)
        member.roles = [blueteam_role]
        member.remove_roles = AsyncMock()

        guild = MagicMock(spec=discord.Guild)
        guild.roles = [blueteam_role]

        with patch("discord.utils.get", return_value=blueteam_role):
            result = await remove_blueteam_role(member, guild, reason="test")

        assert result is True
        member.remove_roles.assert_called_once()

    async def test_remove_blueteam_role_not_found(self) -> None:
        """Test removing Blueteam role when role doesn't exist."""
        member = MagicMock(spec=discord.Member)
        guild = MagicMock(spec=discord.Guild)
        guild.roles = []

        with patch("discord.utils.get", return_value=None):
            result = await remove_blueteam_role(member, guild)

        assert result is True


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestTeamHelpers:
    """Test team helper functions."""

    async def test_get_team_or_respond_success(self, mock_interaction: Any) -> None:
        """Test successfully getting a team."""
        team_num = 25

        # Delete if exists
        await Team.objects.filter(team_number=team_num).adelete()

        await Team.objects.acreate(
            team_number=team_num,
            team_name="Test Team",
            max_members=5,
        )

        result = await get_team_or_respond(mock_interaction, team_num)

        assert result is not None
        assert result.team_number == team_num
        mock_interaction.response.send_message.assert_not_called()

    async def test_get_team_or_respond_not_found(self, mock_interaction: Any) -> None:
        """Test handling team not found."""
        result = await get_team_or_respond(mock_interaction, 42)

        assert result is None
        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "not found" in call_args.args[0].lower()

    async def test_get_team_or_respond_invalid_range(
        self, mock_interaction: Any
    ) -> None:
        """Test handling team number out of range."""
        result = await get_team_or_respond(mock_interaction, 51)

        assert result is None
        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "between 1 and 50" in call_args.args[0]

    async def test_get_team_or_respond_skip_validation(
        self, mock_interaction: Any
    ) -> None:
        """Test skipping range validation."""
        result = await get_team_or_respond(mock_interaction, 99, validate_range=False)

        assert result is None
        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "not found" in call_args.args[0].lower()
        assert "between" not in call_args.args[0].lower()

    async def test_get_team_member_discord_ids(self) -> None:
        """Test getting Discord IDs for team members."""
        team_num = 26

        # Delete if exists
        await Team.objects.filter(team_number=team_num).adelete()

        team = await Team.objects.acreate(
            team_number=team_num,
            team_name="Test Team",
            max_members=5,
        )

        # Create active and inactive members
        await DiscordLink.objects.acreate(
            discord_id=111111111,
            authentik_username="user1",
            authentik_user_id="uid1",
            team=team,
            is_active=True,
        )
        await DiscordLink.objects.acreate(
            discord_id=222222222,
            authentik_username="user2",
            authentik_user_id="uid2",
            team=team,
            is_active=True,
        )
        await DiscordLink.objects.acreate(
            discord_id=333333333,
            authentik_username="user3",
            authentik_user_id="uid3",
            team=team,
            is_active=False,  # Inactive
        )

        discord_ids = await get_team_member_discord_ids(team)

        assert len(discord_ids) == 2
        assert 111111111 in discord_ids
        assert 222222222 in discord_ids
        assert 333333333 not in discord_ids


@pytest.mark.asyncio
class TestLogging:
    """Test logging utility functions."""

    async def test_log_to_ops_channel_success(self) -> None:
        """Test successfully logging to ops channel."""
        channel = AsyncMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        bot = MagicMock(spec=discord.Client)
        bot.get_channel = MagicMock(return_value=channel)

        with patch("bot.utils.settings") as mock_settings:
            mock_settings.DISCORD_LOG_CHANNEL_ID = 123456789
            await log_to_ops_channel(bot, "Test message")

        channel.send.assert_called_once_with("Test message")

    async def test_log_to_ops_channel_with_embed(self) -> None:
        """Test logging to ops channel with embed."""
        channel = AsyncMock(spec=discord.TextChannel)
        channel.send = AsyncMock()

        bot = MagicMock(spec=discord.Client)
        bot.get_channel = MagicMock(return_value=channel)

        embed = discord.Embed(title="Test")

        with patch("bot.utils.settings") as mock_settings:
            mock_settings.DISCORD_LOG_CHANNEL_ID = 123456789
            await log_to_ops_channel(bot, "Test message", embed=embed)

        channel.send.assert_called_once_with("Test message", embed=embed)

    async def test_log_to_ops_channel_no_config(self) -> None:
        """Test logging when channel ID not configured."""
        bot = MagicMock(spec=discord.Client)

        with patch("bot.utils.settings") as mock_settings:
            mock_settings.DISCORD_LOG_CHANNEL_ID = None
            await log_to_ops_channel(bot, "Test message")

        bot.get_channel.assert_not_called()

    async def test_log_to_ops_channel_not_found(self) -> None:
        """Test logging when channel not found."""
        bot = MagicMock(spec=discord.Client)
        bot.get_channel = MagicMock(return_value=None)

        with patch("bot.utils.settings") as mock_settings:
            mock_settings.DISCORD_LOG_CHANNEL_ID = 123456789
            await log_to_ops_channel(bot, "Test message")

        # Should not raise exception, just log error
        bot.get_channel.assert_called_once_with(123456789)
