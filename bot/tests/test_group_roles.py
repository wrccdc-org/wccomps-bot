"""Tests for group role assignment (BlackTeam, WhiteTeam, OrangeTeam, RedTeam)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
import discord
import pytest
from bot.discord_manager import DiscordManager
from bot.discord_queue import DiscordQueueProcessor
from core.models import DiscordTask


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestGroupRoleAssignment:
    """Test assigning special group roles based on Authentik groups."""

    async def test_assign_blackteam_role(self) -> None:
        """Test assigning BlackTeam role based on Authentik group."""
        guild = MagicMock(spec=discord.Guild)
        member = MagicMock(spec=discord.Member)
        member.add_roles = AsyncMock()

        blackteam_role = MagicMock(spec=discord.Role)
        blackteam_role.id = 779192640540639263
        blackteam_role.name = "BlackTeam"

        guild.get_role = MagicMock(return_value=blackteam_role)

        manager = DiscordManager(guild)
        success = await manager.assign_group_roles(member, ["WCComps_BlackTeam"])

        assert success is True
        member.add_roles.assert_called_once()
        call_args = member.add_roles.call_args
        assert blackteam_role in call_args[0]

    async def test_assign_multiple_group_roles(self) -> None:
        """Test assigning multiple group roles at once."""
        guild = MagicMock(spec=discord.Guild)
        member = MagicMock(spec=discord.Member)
        member.add_roles = AsyncMock()

        whiteteam_role = MagicMock(spec=discord.Role)
        whiteteam_role.id = 647838503505362957
        whiteteam_role.name = "WhiteTeam"

        orangeteam_role = MagicMock(spec=discord.Role)
        orangeteam_role.id = 647878925040615446
        orangeteam_role.name = "OrangeTeam"

        def get_role(role_id: int) -> Any:
            if role_id == 647838503505362957:
                return whiteteam_role
            elif role_id == 647878925040615446:
                return orangeteam_role
            return None

        guild.get_role = MagicMock(side_effect=get_role)

        manager = DiscordManager(guild)
        success = await manager.assign_group_roles(
            member, ["WCComps_WhiteTeam", "WCComps_OrangeTeam"]
        )

        assert success is True
        member.add_roles.assert_called_once()
        call_args = member.add_roles.call_args
        assert whiteteam_role in call_args[0]
        assert orangeteam_role in call_args[0]

    async def test_assign_group_roles_missing_role_id(self) -> None:
        """Test handling when configured role ID not found in guild - logs warning."""
        from unittest.mock import patch

        guild = MagicMock(spec=discord.Guild)
        member = MagicMock(spec=discord.Member)
        member.add_roles = AsyncMock()

        guild.get_role = MagicMock(return_value=None)

        manager = DiscordManager(guild)

        with patch("bot.discord_manager.logger") as mock_logger:
            success = await manager.assign_group_roles(member, ["WCComps_BlackTeam"])

            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "not found in guild" in warning_msg

        assert success is True
        member.add_roles.assert_not_called()

    async def test_assign_group_roles_no_matching_groups(self) -> None:
        """Test assigning roles when user has no matching Authentik groups."""
        guild = MagicMock(spec=discord.Guild)
        member = MagicMock(spec=discord.Member)
        member.add_roles = AsyncMock()

        manager = DiscordManager(guild)
        success = await manager.assign_group_roles(member, ["WCComps_BlueTeam01"])

        assert success is True
        member.add_roles.assert_not_called()

    async def test_assign_group_roles_permission_denied(self) -> None:
        """Test handling permission denied when assigning roles."""
        guild = MagicMock(spec=discord.Guild)
        member = MagicMock(spec=discord.Member)

        blackteam_role = MagicMock(spec=discord.Role)
        blackteam_role.id = 779192640540639263
        blackteam_role.name = "BlackTeam"

        guild.get_role = MagicMock(return_value=blackteam_role)

        member.add_roles = AsyncMock(
            side_effect=discord.errors.Forbidden(MagicMock(), "No permission")
        )

        manager = DiscordManager(guild)

        from unittest.mock import patch

        with patch("bot.discord_manager.logger") as mock_logger:
            success = await manager.assign_group_roles(member, ["WCComps_BlackTeam"])

            mock_logger.error.assert_called_once()
            error_msg = mock_logger.error.call_args[0][0]
            assert "No permission" in error_msg

        assert success is False

    async def test_assign_group_roles_http_exception(self) -> None:
        """Test handling HTTP exceptions from Discord API."""
        from unittest.mock import patch

        guild = MagicMock(spec=discord.Guild)
        member = MagicMock(spec=discord.Member)

        role = MagicMock(spec=discord.Role)
        role.id = 779192640540639263
        role.name = "BlackTeam"

        guild.get_role = MagicMock(return_value=role)

        member.add_roles = AsyncMock(
            side_effect=discord.errors.HTTPException(MagicMock(), "API Error")
        )

        manager = DiscordManager(guild)

        with patch("bot.discord_manager.logger") as mock_logger:
            success = await manager.assign_group_roles(member, ["WCComps_BlackTeam"])

            mock_logger.error.assert_called_once()

        assert success is False

    async def test_assign_group_roles_mixed_valid_invalid(self) -> None:
        """Test assigning mix of valid roles and missing roles."""
        from unittest.mock import patch

        guild = MagicMock(spec=discord.Guild)
        member = MagicMock(spec=discord.Member)
        member.add_roles = AsyncMock()

        whiteteam_role = MagicMock(spec=discord.Role)
        whiteteam_role.id = 647838503505362957
        whiteteam_role.name = "WhiteTeam"

        def get_role(role_id: int):
            if role_id == 647838503505362957:
                return whiteteam_role
            return None

        guild.get_role = MagicMock(side_effect=get_role)

        manager = DiscordManager(guild)

        with patch("bot.discord_manager.logger") as mock_logger:
            success = await manager.assign_group_roles(
                member, ["WCComps_WhiteTeam", "WCComps_BlackTeam"]
            )

            mock_logger.warning.assert_called_once()

        assert success is True
        member.add_roles.assert_called_once()
        call_args = member.add_roles.call_args
        assert whiteteam_role in call_args[0]
        assert len(call_args[0]) == 1


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestGroupRoleRemoval:
    """Test removing special group roles."""

    async def test_remove_group_roles(self) -> None:
        """Test removing group roles from member."""
        guild = MagicMock(spec=discord.Guild)
        member = MagicMock(spec=discord.Member)
        member.remove_roles = AsyncMock()

        whiteteam_role = MagicMock(spec=discord.Role)
        whiteteam_role.id = 647838503505362957
        whiteteam_role.name = "WhiteTeam"

        member.roles = [whiteteam_role]
        guild.get_role = MagicMock(return_value=whiteteam_role)

        manager = DiscordManager(guild)
        success = await manager.remove_group_roles(member, ["WCComps_WhiteTeam"])

        assert success is True
        member.remove_roles.assert_called_once()
        call_args = member.remove_roles.call_args
        assert whiteteam_role in call_args[0]

    async def test_remove_multiple_group_roles(self) -> None:
        """Test removing multiple group roles at once."""
        guild = MagicMock(spec=discord.Guild)
        member = MagicMock(spec=discord.Member)
        member.remove_roles = AsyncMock()

        blackteam_role = MagicMock(spec=discord.Role)
        blackteam_role.id = 779192640540639263
        blackteam_role.name = "BlackTeam"

        orangeteam_role = MagicMock(spec=discord.Role)
        orangeteam_role.id = 647878925040615446
        orangeteam_role.name = "OrangeTeam"

        member.roles = [blackteam_role, orangeteam_role]

        role_map = {
            779192640540639263: blackteam_role,
            647878925040615446: orangeteam_role,
        }

        guild.get_role = MagicMock(side_effect=lambda rid: role_map.get(rid))

        manager = DiscordManager(guild)
        success = await manager.remove_group_roles(
            member, ["WCComps_BlackTeam", "WCComps_OrangeTeam"]
        )

        assert success is True
        member.remove_roles.assert_called_once()
        call_args = member.remove_roles.call_args
        assert blackteam_role in call_args[0]
        assert orangeteam_role in call_args[0]

    async def test_remove_group_roles_not_present(self) -> None:
        """Test removing roles that member doesn't have."""
        guild = MagicMock(spec=discord.Guild)
        member = MagicMock(spec=discord.Member)
        member.remove_roles = AsyncMock()

        redteam_role = MagicMock(spec=discord.Role)
        redteam_role.id = 546490269693116437
        redteam_role.name = "RedTeam"

        member.roles = []
        guild.get_role = MagicMock(return_value=redteam_role)

        manager = DiscordManager(guild)
        success = await manager.remove_group_roles(member, ["WCComps_RedTeam"])

        assert success is True
        member.remove_roles.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestGroupRoleQueueProcessing:
    """Test queue processing for group role assignment."""

    async def test_queue_processor_assigns_group_roles(self) -> None:
        """Test that queue processor handles assign_group_roles task."""
        task = await DiscordTask.objects.acreate(
            task_type="assign_group_roles",
            payload={
                "discord_id": 111111111,
                "authentik_groups": ["WCComps_WhiteTeam", "WCComps_OrangeTeam"],
            },
            status="pending",
        )

        bot = AsyncMock(spec=discord.Client)
        guild = MagicMock(spec=discord.Guild)
        guild.id = 525435725123158026

        member = MagicMock(spec=discord.Member)
        member.id = 111111111
        member.add_roles = AsyncMock()

        whiteteam_role = MagicMock(spec=discord.Role)
        whiteteam_role.id = 647838503505362957
        whiteteam_role.name = "WhiteTeam"

        orangeteam_role = MagicMock(spec=discord.Role)
        orangeteam_role.id = 647878925040615446
        orangeteam_role.name = "OrangeTeam"

        role_map = {
            647838503505362957: whiteteam_role,
            647878925040615446: orangeteam_role,
        }

        guild.get_role = MagicMock(side_effect=lambda rid: role_map.get(rid))
        guild.get_member = MagicMock(return_value=member)

        bot.guilds = [guild]

        processor = DiscordQueueProcessor(bot)
        processor.discord_manager = DiscordManager(guild)
        await processor._process_task(task)

        await task.arefresh_from_db()
        assert task.status == "completed"
        member.add_roles.assert_called_once()

    async def test_queue_processor_member_not_found(self) -> None:
        """Test graceful handling when member not found in guild."""
        task = await DiscordTask.objects.acreate(
            task_type="assign_group_roles",
            payload={
                "discord_id": 999999999,
                "authentik_groups": ["WCComps_BlackTeam"],
            },
            status="pending",
        )

        bot = AsyncMock(spec=discord.Client)
        guild = MagicMock(spec=discord.Guild)
        guild.id = 525435725123158026
        guild.get_member = MagicMock(return_value=None)
        bot.guilds = [guild]

        processor = DiscordQueueProcessor(bot)
        processor.discord_manager = DiscordManager(guild)
        await processor._process_task(task)

        await task.arefresh_from_db()
        assert task.status == "completed"

    async def test_queue_processor_missing_discord_id(self) -> None:
        """Test handling missing discord_id in payload."""
        task = await DiscordTask.objects.acreate(
            task_type="assign_group_roles",
            payload={"authentik_groups": ["WCComps_BlackTeam"]},
            status="pending",
        )

        bot = AsyncMock(spec=discord.Client)
        guild = MagicMock(spec=discord.Guild)
        guild.id = 525435725123158026
        bot.guilds = [guild]

        processor = DiscordQueueProcessor(bot)
        processor.discord_manager = DiscordManager(guild)
        await processor._process_task(task)

        await task.arefresh_from_db()
        assert task.status == "pending"
        assert task.retry_count == 1
        assert "discord_id" in task.error_message.lower()
