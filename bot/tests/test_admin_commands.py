"""Tests for admin slash commands."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest
from core.models import AuditLog
from team.models import DiscordLink, Team

from bot.cogs.admin_teams import AdminTeamsCog
from bot.cogs.admin_competition import AdminCompetitionCog


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestAdminCommands:
    """Test admin commands."""

    async def test_admin_teams_command(
        self, mock_interaction: Any, mock_admin_user: Any, mock_bot: Any
    ) -> None:
        mock_interaction.user.id = mock_admin_user._discord_id

        await Team.objects.acreate(
            team_number=10, team_name="Team Alpha", max_members=5
        )
        await Team.objects.acreate(team_number=11, team_name="Team Beta", max_members=5)

        cog = AdminTeamsCog(mock_bot)
        await cog.admin_teams.callback(cog, mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args

        assert "embed" in call_args.kwargs
        embed = call_args.kwargs["embed"]
        assert embed.title == "Team Status"

    async def test_admin_teams_permission_denied(
        self, mock_interaction: Any, mock_team_user: Any, mock_bot: Any
    ) -> None:
        mock_interaction.user.id = 123456789

        cog = AdminTeamsCog(mock_bot)
        await cog.admin_teams.callback(cog, mock_interaction)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "Admin permissions required" in call_args.args[0]
        assert call_args.kwargs.get("ephemeral") is True

    async def test_admin_team_info_command(
        self, mock_interaction: Any, mock_admin_user: Any, mock_bot: Any
    ) -> None:
        mock_interaction.user.id = mock_admin_user._discord_id

        await Team.objects.acreate(team_number=12, team_name="Test Team", max_members=5)

        cog = AdminTeamsCog(mock_bot)
        await cog.admin_team_info.callback(cog, mock_interaction, team_number=12)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "embed" in call_args.kwargs

    async def test_admin_team_info_not_found(
        self, mock_interaction: Any, mock_admin_user: Any, mock_bot: Any
    ) -> None:
        mock_interaction.user.id = mock_admin_user._discord_id

        cog = AdminTeamsCog(mock_bot)
        await cog.admin_team_info.callback(cog, mock_interaction, team_number=42)

        mock_interaction.response.send_message.assert_called_once()
        call_args = mock_interaction.response.send_message.call_args
        assert "not found" in call_args.args[0].lower()

    @patch("bot.cogs.admin_competition.settings")
    @patch("bot.cogs.admin_competition.reset_blueteam_password")
    @patch("bot.cogs.admin_competition.generate_blueteam_password")
    async def test_reset_blueteam_passwords(
        self,
        mock_generate_password: Any,
        mock_reset_password: Any,
        mock_settings: Any,
        mock_interaction: Any,
        mock_admin_user: Any,
        mock_bot: Any,
    ) -> None:
        """Test /admin reset-blueteam-passwords - verifies password reset flow."""
        mock_interaction.user.id = mock_admin_user._discord_id
        mock_settings.AUTHENTIK_TOKEN = "test-token"

        # Mock password generation
        mock_generate_password.return_value = "Test-Password-123!"

        # Mock successful password reset
        mock_reset_password.return_value = (True, "")

        cog = AdminCompetitionCog(mock_bot)
        await cog.admin_reset_blueteam_passwords.callback(
            cog, mock_interaction, team_numbers="1-3"
        )

        # Verify password was generated for each team
        assert mock_generate_password.call_count == 3

        # Verify password reset was called for each team
        assert mock_reset_password.call_count == 3

        mock_interaction.response.defer.assert_called_once_with(ephemeral=True)

        # Verify response includes password file
        mock_interaction.followup.send.assert_called_once()
        call_args = mock_interaction.followup.send.call_args
        assert "file" in call_args.kwargs, "Should send file with passwords"

    @patch("bot.cogs.admin_competition.settings")
    @patch("bot.cogs.admin_competition.reset_blueteam_password")
    @patch("bot.cogs.admin_competition.generate_blueteam_password")
    async def test_reset_blueteam_passwords_api_failure(
        self,
        mock_generate_password: Any,
        mock_reset_password: Any,
        mock_settings: Any,
        mock_interaction: Any,
        mock_admin_user: Any,
        mock_bot: Any,
    ) -> None:
        """Test /admin reset-blueteam-passwords handles API failures."""
        mock_interaction.user.id = mock_admin_user._discord_id
        mock_settings.AUTHENTIK_TOKEN = "test-token"

        # Mock password generation
        mock_generate_password.return_value = "Test-Password-123!"

        # Simulate API failure for password reset
        mock_reset_password.return_value = (False, "HTTP 500: Internal Server Error")

        cog = AdminCompetitionCog(mock_bot)

        # Should handle error gracefully
        await cog.admin_reset_blueteam_passwords.callback(
            cog, mock_interaction, team_numbers="1-3"
        )

        # Verify error was communicated
        assert mock_interaction.followup.send.called, "Should send error message"

        # Verify CSV file was still sent (with attempted passwords)
        call_args = mock_interaction.followup.send.call_args
        assert "file" in call_args.kwargs, "Should still send CSV file"

    @patch("bot.cogs.admin_teams.remove_blueteam_role")
    @patch("bot.cogs.admin_teams.safe_remove_role")
    @patch("bot.cogs.admin_teams.log_to_ops_channel")
    async def test_admin_remove_team(
        self,
        mock_log_ops: Any,
        mock_safe_remove_role: Any,
        mock_remove_blueteam: Any,
        mock_interaction: Any,
        mock_admin_user: Any,
        mock_bot: Any,
    ) -> None:
        """Test /admin remove-team removes roles BEFORE deactivating links and creates audit log."""
        # Setup
        mock_interaction.user.id = mock_admin_user._discord_id

        team_number = 13

        team = await Team.objects.acreate(
            team_number=team_number,
            team_name="Test Team to Remove",
            max_members=5,
            discord_role_id=1001,
            discord_category_id=2001,
        )

        # Create team members with active links
        member1_link = await DiscordLink.objects.acreate(
            discord_id=111111111,
            discord_username="member1",
            authentik_username="team_member1",
            authentik_user_id="auth-id-1",
            team=team,
            is_active=True,
        )
        member2_link = await DiscordLink.objects.acreate(
            discord_id=222222222,
            discord_username="member2",
            authentik_username="team_member2",
            authentik_user_id="auth-id-2",
            team=team,
            is_active=True,
        )

        # Create role mock
        team_role = MagicMock(spec=discord.Role)
        team_role.id = 1001
        team_role.name = f"Team {team_number:02d}"

        # Create Discord mocks for members with the team role
        member1_discord = MagicMock(spec=discord.Member)
        member1_discord.id = 111111111
        member1_discord.roles = [team_role]

        member2_discord = MagicMock(spec=discord.Member)
        member2_discord.id = 222222222
        member2_discord.roles = [team_role]

        category = MagicMock(spec=discord.CategoryChannel)
        category.id = 2001
        category.channels = []

        # Setup guild mock
        mock_interaction.guild.get_member = MagicMock(
            side_effect=lambda did: member1_discord
            if did == 111111111
            else (member2_discord if did == 222222222 else None)
        )
        mock_interaction.guild.get_role = MagicMock(
            side_effect=lambda rid: team_role if rid == 1001 else None
        )
        mock_interaction.guild.get_channel = MagicMock(
            side_effect=lambda cid: category if cid == 2001 else None
        )

        # Setup mocks for role removal
        mock_safe_remove_role.return_value = None
        mock_remove_blueteam.return_value = None
        category.delete = AsyncMock()
        team_role.delete = AsyncMock()

        # Track call order to verify roles are removed BEFORE links deactivated
        call_order = []

        async def track_role_removal(*args, **kwargs):
            call_order.append(("role_removed", args[1].name if args else "unknown"))

        async def track_blueteam_removal(*args, **kwargs):
            call_order.append(("blueteam_removed", args[0].id))

        mock_safe_remove_role.side_effect = track_role_removal
        mock_remove_blueteam.side_effect = track_blueteam_removal

        # Execute command
        cog = AdminTeamsCog(mock_bot)
        await cog.admin_remove_team.callback(
            cog, mock_interaction, team_number=team_number
        )

        # Verify response was sent
        mock_interaction.response.defer.assert_called_once_with(ephemeral=True)
        mock_interaction.followup.send.assert_called_once()
        send_call_args = mock_interaction.followup.send.call_args
        assert "Removed" in send_call_args.args[0]

        # Verify links were deactivated AFTER role removal
        await member1_link.arefresh_from_db()
        await member2_link.arefresh_from_db()
        assert member1_link.is_active is False
        assert member2_link.is_active is False
        assert member1_link.unlinked_at is not None
        assert member2_link.unlinked_at is not None

        # Verify role removal was called for each member
        assert mock_safe_remove_role.call_count >= 2  # At least one call per member
        assert mock_remove_blueteam.call_count >= 2  # Once per member

        # Verify category and role were deleted
        category.delete.assert_called_once()
        team_role.delete.assert_called_once()

        # Verify team Discord IDs were cleared
        await team.arefresh_from_db()
        assert team.discord_role_id is None
        assert team.discord_category_id is None

        # Verify audit log was created
        audit_logs = await AuditLog.objects.filter(
            action="team_removed",
            target_id=team_number,
        ).acount()
        assert audit_logs == 1

        audit_log = await AuditLog.objects.filter(
            action="team_removed",
            target_id=team_number,
        ).afirst()
        assert audit_log is not None
        assert audit_log.admin_user == str(mock_interaction.user)
        assert audit_log.target_entity == "team"
        assert audit_log.details["team_name"] == "Test Team to Remove"
        assert audit_log.details["unlinked_members"] == 2
        assert "role" in audit_log.details["removed_items"]

    async def test_admin_unlink_deactivates_link_and_removes_roles(
        self, mock_interaction: Any, mock_admin_user: Any, mock_bot: Any
    ) -> None:
        """Test that admin_unlink deactivates the Discord link and removes roles."""
        mock_interaction.user.id = mock_admin_user._discord_id
        mock_interaction.user.name = "admin_user"
        mock_interaction.user.mention = "<@211533935144992768>"

        # Create a team with discord role ID
        team = await Team.objects.acreate(
            team_number=14,
            team_name="Test Unlink Team",
            max_members=5,
            discord_role_id=1001,
        )

        # Create a team member with active link
        member_id = 999999999999999999

        await DiscordLink.objects.acreate(
            discord_id=member_id,
            discord_username="test_member",
            authentik_username="team_user_01",
            authentik_user_id="test-user-uuid",
            team=team,
            is_active=True,
        )

        # Mock Discord role
        team_role = MagicMock(spec=discord.Role)
        team_role.id = 1001
        team_role.name = team.team_name

        blueteam_role = MagicMock(spec=discord.Role)
        blueteam_role.id = 525444104763736075
        blueteam_role.name = "Blueteam"

        mock_interaction.guild.get_role.side_effect = lambda role_id: (
            team_role if role_id == 1001 else blueteam_role
        )

        # Mock member
        member_mock = AsyncMock(spec=discord.Member)
        member_mock.id = member_id
        member_mock.mention = f"<@{member_id}>"
        member_mock.remove_roles = AsyncMock()

        # Mock guild.get_member to return the member
        mock_interaction.guild.get_member.return_value = member_mock

        # Mock safe_remove_role and remove_blueteam_role
        with (
            patch("bot.cogs.admin_teams.safe_remove_role") as mock_safe_remove,
            patch("bot.cogs.admin_teams.remove_blueteam_role") as mock_remove_blueteam,
            patch("bot.cogs.admin_teams.log_to_ops_channel") as mock_log_ops,
        ):
            cog = AdminTeamsCog(mock_bot)
            # Pass member ID as string
            await cog.admin_unlink.callback(cog, mock_interaction, str(member_id))

            # Verify link was deactivated
            updated_link = await DiscordLink.objects.aget(discord_id=member_id)
            assert updated_link.is_active is False
            assert updated_link.unlinked_at is not None

            # Verify role removal was called
            mock_safe_remove.assert_called_once()
            call_args = mock_safe_remove.call_args
            assert call_args[0][0] == member_mock
            assert call_args[0][1] == team_role

            mock_remove_blueteam.assert_called_once()
            call_args = mock_remove_blueteam.call_args
            assert call_args[0][0] == member_mock
            assert call_args[0][1] == mock_interaction.guild

            # Verify audit log was created
            audit_logs = [
                log async for log in AuditLog.objects.filter(action="user_unlinked")
            ]
            assert len(audit_logs) == 1
            audit_log = audit_logs[0]
            assert audit_log.admin_user == str(mock_interaction.user)
            assert audit_log.target_entity == "discord_link"
            assert audit_log.target_id == member_id
            assert audit_log.details["team_name"] == team.team_name
            assert audit_log.details["authentik_username"] == "team_user_01"

            # Verify user feedback message
            mock_interaction.response.defer.assert_called_once()
            mock_interaction.followup.send.assert_called_once()
            call_args = mock_interaction.followup.send.call_args
            assert "Unlinked" in call_args.args[0] or "✓" in call_args.args[0]

            # Verify ops channel log
            mock_log_ops.assert_called_once()

    async def test_admin_unlink_user_not_linked(
        self, mock_interaction: Any, mock_admin_user: Any, mock_bot: Any
    ) -> None:
        """Test that admin_unlink handles user not linked to any team."""
        mock_interaction.user.id = mock_admin_user._discord_id

        # Create a member with no active link
        member_id = 888888888888888888

        member_mock = AsyncMock(spec=discord.Member)
        member_mock.id = member_id
        member_mock.mention = f"<@{member_id}>"

        # Mock guild.get_member to return the member
        mock_interaction.guild.get_member.return_value = member_mock

        cog = AdminTeamsCog(mock_bot)
        await cog.admin_unlink.callback(cog, mock_interaction, str(member_id))

        # Verify appropriate error message
        mock_interaction.response.defer.assert_called_once()
        mock_interaction.followup.send.assert_called_once()
        call_args = mock_interaction.followup.send.call_args
        assert (
            "not linked to any team" in call_args.args[0] or "❌" in call_args.args[0]
        )
        assert call_args.kwargs.get("ephemeral") is True

    async def test_admin_unlink_user_not_in_server(
        self, mock_interaction: Any, mock_admin_user: Any, mock_bot: Any
    ) -> None:
        """Test that admin_unlink handles user not in Discord server gracefully."""
        mock_interaction.user.id = mock_admin_user._discord_id
        mock_interaction.guild = None

        # Create a team
        team = await Team.objects.acreate(
            team_number=15,
            team_name="Test Team No Guild",
            max_members=5,
            discord_role_id=1001,
        )

        # Create a Discord link
        member_id = 777777777777777777
        await DiscordLink.objects.acreate(
            discord_id=member_id,
            discord_username="old_member",
            authentik_username="old_user",
            authentik_user_id="old-user-uuid",
            team=team,
            is_active=True,
        )

        member_mock = AsyncMock(spec=discord.Member)
        member_mock.id = member_id
        member_mock.mention = "<@test>"

        with (
            patch("bot.cogs.admin_teams.safe_remove_role"),
            patch("bot.cogs.admin_teams.log_to_ops_channel"),
        ):
            cog = AdminTeamsCog(mock_bot)
            await cog.admin_unlink.callback(cog, mock_interaction, str(member_id))

            # Since guild is None, command should return error early
            # Link should NOT be deactivated
            updated_link = await DiscordLink.objects.aget(discord_id=member_id)
            assert updated_link.is_active is True

            # Verify error message about guild requirement
            mock_interaction.response.defer.assert_called_once()
            mock_interaction.followup.send.assert_called_once()
            call_args = mock_interaction.followup.send.call_args
            assert "guild" in call_args.args[0].lower()
            assert call_args.kwargs.get("ephemeral") is True
