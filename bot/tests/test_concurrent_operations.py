"""Tests for concurrent role assignment operations."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from bot.discord_manager import DiscordManager
from bot.discord_queue import DiscordQueueProcessor
from core.models import DiscordTask


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestConcurrentGroupRoleAssignments:
    """Test concurrent group role assignments don't create conflicts."""

    async def test_concurrent_assign_same_user_different_roles(self) -> None:
        """Test concurrent assignments of different group roles to same user."""
        guild = MagicMock(spec=discord.Guild)
        member = MagicMock(spec=discord.Member)
        member.id = 111111111
        member.add_roles = AsyncMock()

        whiteteam_role = MagicMock(spec=discord.Role)
        whiteteam_role.id = 647838503505362957
        whiteteam_role.name = "WhiteTeam"

        blackteam_role = MagicMock(spec=discord.Role)
        blackteam_role.id = 779192640540639263
        blackteam_role.name = "BlackTeam"

        role_map = {
            647838503505362957: whiteteam_role,
            779192640540639263: blackteam_role,
        }

        guild.get_role = MagicMock(side_effect=lambda rid: role_map.get(rid))

        manager = DiscordManager(guild)

        # Run two concurrent role assignments
        results = await asyncio.gather(
            manager.assign_group_roles(member, ["WCComps_WhiteTeam"]),
            manager.assign_group_roles(member, ["WCComps_BlackTeam"]),
        )

        assert all(results)  # Both should succeed

        # Verify both roles were assigned (check calls contain both roles)
        all_calls = member.add_roles.call_args_list
        assigned_roles = set()
        for call in all_calls:
            assigned_roles.update(call[0])

        assert whiteteam_role in assigned_roles, "WhiteTeam role should be assigned"
        assert blackteam_role in assigned_roles, "BlackTeam role should be assigned"

    async def test_concurrent_assign_different_users(self) -> None:
        """Test concurrent assignments to different users don't interfere."""
        guild = MagicMock(spec=discord.Guild)

        member1 = MagicMock(spec=discord.Member)
        member1.id = 111111111
        member1.add_roles = AsyncMock()

        member2 = MagicMock(spec=discord.Member)
        member2.id = 222222222
        member2.add_roles = AsyncMock()

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

        manager = DiscordManager(guild)

        # Assign different roles to different users concurrently
        results = await asyncio.gather(
            manager.assign_group_roles(member1, ["WCComps_WhiteTeam"]),
            manager.assign_group_roles(member2, ["WCComps_OrangeTeam"]),
        )

        assert all(results)
        member1.add_roles.assert_called_once()
        member2.add_roles.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestConcurrentQueueProcessing:
    """Test concurrent queue task processing."""

    async def test_concurrent_queue_tasks_different_users(self) -> None:
        """Test processing multiple queue tasks for different users concurrently."""
        task1 = await DiscordTask.objects.acreate(
            task_type="assign_group_roles",
            payload={
                "discord_id": 111111111,
                "authentik_groups": ["WCComps_WhiteTeam"],
            },
            status="pending",
        )

        task2 = await DiscordTask.objects.acreate(
            task_type="assign_group_roles",
            payload={
                "discord_id": 222222222,
                "authentik_groups": ["WCComps_OrangeTeam"],
            },
            status="pending",
        )

        bot = AsyncMock(spec=discord.Client)
        guild = MagicMock(spec=discord.Guild)
        guild.id = 525435725123158026

        member1 = MagicMock(spec=discord.Member)
        member1.id = 111111111
        member1.add_roles = AsyncMock()

        member2 = MagicMock(spec=discord.Member)
        member2.id = 222222222
        member2.add_roles = AsyncMock()

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

        def get_member(member_id: int) -> Any:
            if member_id == 111111111:
                return member1
            if member_id == 222222222:
                return member2
            return None

        guild.get_role = MagicMock(side_effect=lambda rid: role_map.get(rid))
        guild.get_member = MagicMock(side_effect=get_member)

        bot.guilds = [guild]

        processor = DiscordQueueProcessor(bot)
        processor.discord_manager = DiscordManager(guild)

        # Process both tasks concurrently
        await asyncio.gather(
            processor._process_task(task1),
            processor._process_task(task2),
        )

        await task1.arefresh_from_db()
        await task2.arefresh_from_db()

        assert task1.status == "completed"
        assert task2.status == "completed"
        member1.add_roles.assert_called_once()
        member2.add_roles.assert_called_once()

    async def test_concurrent_queue_tasks_same_user(self) -> None:
        """Test processing multiple queue tasks for same user concurrently."""
        task1 = await DiscordTask.objects.acreate(
            task_type="assign_group_roles",
            payload={
                "discord_id": 111111111,
                "authentik_groups": ["WCComps_WhiteTeam"],
            },
            status="pending",
        )

        task2 = await DiscordTask.objects.acreate(
            task_type="assign_group_roles",
            payload={
                "discord_id": 111111111,
                "authentik_groups": ["WCComps_BlackTeam"],
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

        blackteam_role = MagicMock(spec=discord.Role)
        blackteam_role.id = 779192640540639263
        blackteam_role.name = "BlackTeam"

        role_map = {
            647838503505362957: whiteteam_role,
            779192640540639263: blackteam_role,
        }

        guild.get_role = MagicMock(side_effect=lambda rid: role_map.get(rid))
        guild.get_member = MagicMock(return_value=member)

        bot.guilds = [guild]

        processor = DiscordQueueProcessor(bot)
        processor.discord_manager = DiscordManager(guild)

        # Process both tasks concurrently for same user
        await asyncio.gather(
            processor._process_task(task1),
            processor._process_task(task2),
        )

        await task1.arefresh_from_db()
        await task2.arefresh_from_db()

        assert task1.status == "completed"
        assert task2.status == "completed"

        # Verify both roles were assigned
        all_calls = member.add_roles.call_args_list
        assigned_roles = set()
        for call in all_calls:
            assigned_roles.update(call[0])

        assert whiteteam_role in assigned_roles, "WhiteTeam role should be assigned"
        assert blackteam_role in assigned_roles, "BlackTeam role should be assigned"


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestConcurrentTeamAndGroupRoles:
    """Test concurrent team role and group role operations."""

    async def test_concurrent_team_and_group_role_assignment(self) -> None:
        """Test assigning team role and group role concurrently."""
        guild = MagicMock(spec=discord.Guild)
        member = MagicMock(spec=discord.Member)
        member.add_roles = AsyncMock()

        team_role = MagicMock(spec=discord.Role)
        team_role.id = 5001
        team_role.name = "Team 50"

        whiteteam_role = MagicMock(spec=discord.Role)
        whiteteam_role.id = 647838503505362957
        whiteteam_role.name = "WhiteTeam"

        role_map = {
            5001: team_role,
            647838503505362957: whiteteam_role,
        }

        guild.get_role = MagicMock(side_effect=lambda rid: role_map.get(rid))

        manager = DiscordManager(guild)

        # Concurrently assign team role and group role
        async def assign_team_role() -> bool:
            role = guild.get_role(5001)
            if role:
                await member.add_roles(role, reason="Team assignment")
                return True
            return False

        async def assign_group_role() -> bool:
            return await manager.assign_group_roles(member, ["WCComps_WhiteTeam"])

        results = await asyncio.gather(
            assign_team_role(),
            assign_group_role(),
        )

        assert all(results)

        # Verify both roles were assigned
        all_calls = member.add_roles.call_args_list
        assigned_roles = set()
        for call in all_calls:
            assigned_roles.update(call[0])

        assert team_role in assigned_roles, "Team role should be assigned"
        assert whiteteam_role in assigned_roles, "WhiteTeam role should be assigned"
