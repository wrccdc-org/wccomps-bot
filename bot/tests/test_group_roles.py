"""Tests for group role assignment (BlackTeam, WhiteTeam, OrangeTeam, RedTeam)."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from asgiref.sync import sync_to_async

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
            if role_id == 647878925040615446:
                return orangeteam_role
            return None

        guild.get_role = MagicMock(side_effect=get_role)

        manager = DiscordManager(guild)
        success = await manager.assign_group_roles(member, ["WCComps_WhiteTeam", "WCComps_OrangeTeam"])

        assert success is True
        member.add_roles.assert_called_once()
        call_args = member.add_roles.call_args
        assert whiteteam_role in call_args[0]
        assert orangeteam_role in call_args[0]

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
            success = await manager.assign_group_roles(member, ["WCComps_WhiteTeam", "WCComps_BlackTeam"])

            mock_logger.warning.assert_called_once()

        assert success is True
        member.add_roles.assert_called_once()
        call_args = member.add_roles.call_args
        assert whiteteam_role in call_args[0]
        assert len(call_args[0]) == 1


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
        guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(), "Member not found"))
        bot.guilds = [guild]

        processor = DiscordQueueProcessor(bot)
        processor.discord_manager = DiscordManager(guild)
        await processor._process_task(task)

        await task.arefresh_from_db()
        assert task.status == "completed"

    async def test_queue_processor_missing_discord_id(self) -> None:
        """Test handling missing discord_id in payload."""
        # Use bulk_create to bypass save() validation — this simulates a
        # malformed task that somehow made it into the DB.
        tasks = await sync_to_async(DiscordTask.objects.bulk_create)(
            [
                DiscordTask(
                    task_type="assign_group_roles",
                    payload={"authentik_groups": ["WCComps_BlackTeam"]},
                    status="pending",
                )
            ]
        )
        task = tasks[0]

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
