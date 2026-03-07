"""Tests for role synchronization between guilds."""

from unittest.mock import AsyncMock, MagicMock, patch

import discord

from bot.role_sync import RoleSyncManager


class TestRoleSync:
    """Test role synchronization functionality."""

    async def test_sync_roles_adds_missing_roles(self) -> None:
        """Test that users with roles in volunteer guild get them in competition guild."""
        # Create mock bot
        mock_bot = MagicMock()

        # Create mock guilds
        volunteer_guild = MagicMock(spec=discord.Guild)
        volunteer_guild.id = 404855247857778697
        volunteer_guild.name = "Volunteer Guild"

        competition_guild = MagicMock(spec=discord.Guild)
        competition_guild.id = 123456789
        competition_guild.name = "Competition Guild"
        competition_guild.chunk = AsyncMock()

        mock_bot.get_guild.side_effect = lambda gid: volunteer_guild if gid == 404855247857778697 else competition_guild

        # Create mock roles
        volunteer_role = MagicMock(spec=discord.Role)
        volunteer_role.id = 440383982753021972
        volunteer_role.name = "Operations team"

        competition_role = MagicMock(spec=discord.Role)
        competition_role.id = 779192640540639263
        competition_role.name = "BlackTeam"

        # Create mock members
        member_with_role = MagicMock(spec=discord.Member)
        member_with_role.id = 111111111
        member_with_role.name = "test_user"
        member_with_role.bot = False
        member_with_role.roles = []
        member_with_role.add_roles = AsyncMock()

        # Member has role in volunteer guild
        volunteer_role.members = [member_with_role]
        volunteer_guild.get_role.return_value = volunteer_role

        # Member doesn't have role in competition guild yet
        competition_guild.get_role.return_value = competition_role
        competition_guild.members = [member_with_role]

        # Mock settings
        with patch("bot.role_sync.settings") as mock_settings:
            mock_settings.VOLUNTEER_GUILD_ID = 404855247857778697
            mock_settings.COMPETITION_GUILD_ID = 123456789
            mock_settings.ROLE_SYNC_MAPPING = {440383982753021972: 779192640540639263}

            # Create role sync manager
            role_sync = RoleSyncManager(mock_bot)

            # Run sync
            stats = await role_sync.sync_roles()

            # Verify role was added
            assert stats["roles_added"] == 1
            assert stats["roles_removed"] == 0
            assert stats["errors"] == 0
            assert len(stats["changes"]) == 1
            assert "Added" in stats["changes"][0]
            assert "test_user" in stats["changes"][0]

            member_with_role.add_roles.assert_called_once_with(
                competition_role,
                reason="Role sync: has Operations team in volunteer guild",
            )

    async def test_sync_roles_removes_extra_roles(self) -> None:
        """Test that users without roles in volunteer guild lose them in competition guild."""
        # Create mock bot
        mock_bot = MagicMock()

        # Create mock guilds
        volunteer_guild = MagicMock(spec=discord.Guild)
        volunteer_guild.id = 404855247857778697
        volunteer_guild.name = "Volunteer Guild"

        competition_guild = MagicMock(spec=discord.Guild)
        competition_guild.id = 123456789
        competition_guild.name = "Competition Guild"
        competition_guild.chunk = AsyncMock()

        mock_bot.get_guild.side_effect = lambda gid: volunteer_guild if gid == 404855247857778697 else competition_guild

        # Create mock roles
        volunteer_role = MagicMock(spec=discord.Role)
        volunteer_role.id = 440383982753021972
        volunteer_role.name = "Operations team"
        volunteer_role.members = []  # No members with role

        competition_role = MagicMock(spec=discord.Role)
        competition_role.id = 779192640540639263
        competition_role.name = "BlackTeam"

        # Create mock member
        member_with_old_role = MagicMock(spec=discord.Member)
        member_with_old_role.id = 222222222
        member_with_old_role.name = "old_user"
        member_with_old_role.bot = False
        member_with_old_role.roles = [competition_role]  # Has role in competition
        member_with_old_role.remove_roles = AsyncMock()

        volunteer_guild.get_role.return_value = volunteer_role
        competition_guild.get_role.return_value = competition_role
        competition_guild.members = [member_with_old_role]

        # Mock settings
        with patch("bot.role_sync.settings") as mock_settings:
            mock_settings.VOLUNTEER_GUILD_ID = 404855247857778697
            mock_settings.COMPETITION_GUILD_ID = 123456789
            mock_settings.ROLE_SYNC_MAPPING = {440383982753021972: 779192640540639263}

            # Create role sync manager
            role_sync = RoleSyncManager(mock_bot)

            # Run sync
            stats = await role_sync.sync_roles()

            # Verify role was removed
            assert stats["roles_added"] == 0
            assert stats["roles_removed"] == 1
            assert stats["errors"] == 0
            assert len(stats["changes"]) == 1
            assert "Removed" in stats["changes"][0]
            assert "old_user" in stats["changes"][0]

            member_with_old_role.remove_roles.assert_called_once_with(
                competition_role,
                reason="Role sync: no longer has Operations team in volunteer guild",
            )

    async def test_sync_roles_skips_bots(self) -> None:
        """Test that bot users are skipped during role sync."""
        # Create mock bot
        mock_bot = MagicMock()

        # Create mock guilds
        volunteer_guild = MagicMock(spec=discord.Guild)
        volunteer_guild.id = 404855247857778697
        volunteer_guild.name = "Volunteer Guild"

        competition_guild = MagicMock(spec=discord.Guild)
        competition_guild.id = 123456789
        competition_guild.name = "Competition Guild"
        competition_guild.chunk = AsyncMock()

        mock_bot.get_guild.side_effect = lambda gid: volunteer_guild if gid == 404855247857778697 else competition_guild

        # Create mock roles
        volunteer_role = MagicMock(spec=discord.Role)
        volunteer_role.id = 440383982753021972
        volunteer_role.name = "Operations team"
        volunteer_role.members = []

        competition_role = MagicMock(spec=discord.Role)
        competition_role.id = 779192640540639263
        competition_role.name = "BlackTeam"

        # Create mock bot member
        bot_member = MagicMock(spec=discord.Member)
        bot_member.id = 999999999
        bot_member.name = "bot_user"
        bot_member.bot = True
        bot_member.roles = [competition_role]
        bot_member.remove_roles = AsyncMock()

        volunteer_guild.get_role.return_value = volunteer_role
        competition_guild.get_role.return_value = competition_role
        competition_guild.members = [bot_member]

        # Mock settings
        with patch("bot.role_sync.settings") as mock_settings:
            mock_settings.VOLUNTEER_GUILD_ID = 404855247857778697
            mock_settings.COMPETITION_GUILD_ID = 123456789
            mock_settings.ROLE_SYNC_MAPPING = {440383982753021972: 779192640540639263}

            # Create role sync manager
            role_sync = RoleSyncManager(mock_bot)

            # Run sync
            stats = await role_sync.sync_roles()

            # Verify bot was skipped
            assert stats["roles_added"] == 0
            assert stats["roles_removed"] == 0
            assert stats["errors"] == 0
            assert len(stats["changes"]) == 0

            bot_member.remove_roles.assert_not_called()

    async def test_sync_roles_handles_missing_guild(self) -> None:
        """Test that sync gracefully handles missing guilds."""
        # Create mock bot with no guilds
        mock_bot = MagicMock()
        mock_bot.get_guild.return_value = None

        # Mock settings
        with patch("bot.role_sync.settings") as mock_settings:
            mock_settings.VOLUNTEER_GUILD_ID = 404855247857778697
            mock_settings.COMPETITION_GUILD_ID = 123456789
            mock_settings.ROLE_SYNC_MAPPING = {440383982753021972: 779192640540639263}

            # Create role sync manager
            role_sync = RoleSyncManager(mock_bot)

            # Run sync
            stats = await role_sync.sync_roles()

            # Verify error was reported
            assert stats["roles_added"] == 0
            assert stats["roles_removed"] == 0
            assert stats["errors"] == 1
            assert len(stats["changes"]) == 0
