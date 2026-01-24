"""Role synchronization between volunteer and competition Discord guilds."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TypedDict

import discord
from asgiref.sync import sync_to_async
from django.conf import settings

logger = logging.getLogger(__name__)


class RoleSyncStats(TypedDict, total=False):
    """Statistics for role synchronization."""

    roles_added: int
    roles_removed: int
    errors: int
    changes: list[str]


class RoleSyncManager:
    """Manages role synchronization from volunteer guild to competition guild."""

    def __init__(self, bot: discord.Client) -> None:
        """Initialize role sync manager.

        Args:
            bot: Discord bot instance with access to both guilds
        """
        self.bot = bot
        self.volunteer_guild_id = settings.VOLUNTEER_GUILD_ID
        self.competition_guild_id = settings.COMPETITION_GUILD_ID
        self.role_mappings = settings.ROLE_SYNC_MAPPING

    def _get_guilds(self) -> tuple[discord.Guild | None, discord.Guild | None]:
        """Get volunteer and competition guild objects.

        Returns:
            tuple[Optional[Guild], Optional[Guild]]: (volunteer_guild, competition_guild)
        """
        volunteer_guild = self.bot.get_guild(self.volunteer_guild_id)
        competition_guild = self.bot.get_guild(self.competition_guild_id)

        if not volunteer_guild:
            logger.error(f"Volunteer guild {self.volunteer_guild_id} not found")
        if not competition_guild:
            logger.error(f"Competition guild {self.competition_guild_id} not found")

        return volunteer_guild, competition_guild

    async def sync_roles(
        self,
        progress_callback: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> RoleSyncStats:
        """Synchronize roles from volunteer guild to competition guild.

        This performs one-way sync: volunteer guild -> competition guild.
        - Users with roles in volunteer guild get them added in competition guild
        - Users without roles in volunteer guild get them removed from competition guild

        Args:
            progress_callback: Optional async callback(current, total, role_name) for progress updates

        Returns:
            dict with sync statistics: roles_added, roles_removed, errors, changes
        """
        volunteer_guild, competition_guild = self._get_guilds()
        if not volunteer_guild or not competition_guild:
            return {"roles_added": 0, "roles_removed": 0, "errors": 1, "changes": []}

        stats: RoleSyncStats = {
            "roles_added": 0,
            "roles_removed": 0,
            "errors": 0,
            "changes": [],
        }

        logger.info("=" * 80)
        logger.info("ROLE SYNC STARTED")
        logger.info(f"Volunteer Guild: {volunteer_guild.name} (ID: {volunteer_guild.id})")
        logger.info(f"Competition Guild: {competition_guild.name} (ID: {competition_guild.id})")
        logger.info(f"Role Mappings: {len(self.role_mappings)} configured")
        for v_role_id, c_role_id in self.role_mappings.items():
            logger.info(f"  - {v_role_id} -> {c_role_id}")
        logger.info("=" * 80)

        # Chunk competition guild once at the start to get all members
        cached_member_count = len(competition_guild.members)
        logger.info(
            f"Fetching all members from competition guild "
            f"(currently have {cached_member_count} cached, chunked={competition_guild.chunked})..."
        )
        if not competition_guild.chunked:
            chunk_start = time.time()
            try:
                await asyncio.wait_for(competition_guild.chunk(), timeout=30.0)
                chunk_duration = time.time() - chunk_start
                logger.info(f"Guild chunk completed in {chunk_duration:.2f}s")
            except TimeoutError:
                chunk_duration = time.time() - chunk_start
                logger.warning(
                    f"Guild chunk timed out after {chunk_duration:.2f}s, "
                    f"using cached members ({len(competition_guild.members)} available)"
                )
        else:
            logger.info("Guild already chunked, skipping chunk request")
        logger.info(f"Competition guild has {len(competition_guild.members)} total members")

        # Process each role mapping
        total_mappings = len(self.role_mappings)
        for idx, (volunteer_role_id, competition_role_id) in enumerate(self.role_mappings.items(), start=1):
            # Get role name for progress reporting
            competition_role = competition_guild.get_role(competition_role_id)
            role_name = competition_role.name if competition_role else f"Role {competition_role_id}"

            # Report progress via callback if provided
            if progress_callback:
                await progress_callback(idx, total_mappings, role_name)

            try:
                await self._sync_role_pair(
                    volunteer_guild,
                    competition_guild,
                    volunteer_role_id,
                    competition_role_id,
                    stats,
                )
            except Exception as e:
                logger.error(
                    f"Error syncing role {volunteer_role_id} -> {competition_role_id}: {e}",
                    exc_info=True,
                )
                stats["errors"] = stats["errors"] + 1

        logger.info("=" * 80)
        logger.info("ROLE SYNC COMPLETE")
        logger.info(f"Roles Added: {stats['roles_added']}")
        logger.info(f"Roles Removed: {stats['roles_removed']}")
        logger.info(f"Errors: {stats['errors']}")
        changes = stats.get("changes", [])
        if isinstance(changes, list):
            logger.info(f"Total Changes: {len(changes)}")
        logger.info("=" * 80)
        return stats

    async def _sync_role_pair(
        self,
        volunteer_guild: discord.Guild,
        competition_guild: discord.Guild,
        volunteer_role_id: int,
        competition_role_id: int,
        stats: RoleSyncStats,
    ) -> None:
        """Sync a single role pair between guilds.

        Args:
            volunteer_guild: Source guild with volunteer roles
            competition_guild: Target guild where roles should be synced
            volunteer_role_id: Role ID in volunteer guild to sync from
            competition_role_id: Role ID in competition guild to sync to
            stats: Statistics dict to update
        """
        volunteer_role = volunteer_guild.get_role(volunteer_role_id)
        competition_role = competition_guild.get_role(competition_role_id)

        if not volunteer_role:
            logger.warning(f"Volunteer role {volunteer_role_id} not found in {volunteer_guild.name}")
            return

        if not competition_role:
            logger.warning(f"Competition role {competition_role_id} not found in {competition_guild.name}")
            return

        logger.info("-" * 80)
        logger.info(
            f"Syncing: {volunteer_role.name} (ID: {volunteer_role_id}, {volunteer_guild.name}) -> "
            f"{competition_role.name} (ID: {competition_role_id}, {competition_guild.name})"
        )

        # Get members with role in volunteer guild
        volunteer_members_with_role = {m.id for m in volunteer_role.members}
        logger.info(f"Members with {volunteer_role.name} in volunteer guild: {len(volunteer_members_with_role)}")
        if volunteer_members_with_role:
            logger.debug(f"  Member IDs: {volunteer_members_with_role}")

        # Competition guild was already chunked at the start of sync_roles()
        logger.info(f"Processing {len(competition_guild.members)} competition guild members")

        members_checked = 0
        members_skipped_bot = 0
        members_no_action = 0

        for member in competition_guild.members:
            if member.bot:
                members_skipped_bot += 1
                logger.debug(f"Skipping bot user: {member.name} (ID: {member.id})")
                continue

            members_checked += 1

            try:
                should_have_role = member.id in volunteer_members_with_role
                has_role = competition_role in member.roles

                logger.debug(
                    f"Checking {member.name} (ID: {member.id}): should_have={should_have_role}, has={has_role}"
                )

                if should_have_role and not has_role:
                    # Add role
                    logger.info(
                        f"Adding {competition_role.name} to {member.name} (ID: {member.id}, "
                        f"display: {member.display_name})"
                    )
                    await member.add_roles(
                        competition_role,
                        reason=f"Role sync: has {volunteer_role.name} in volunteer guild",
                    )
                    change_msg = f"Added {competition_role.name} to {member.name} ({member.display_name})"
                    logger.info(f"✓ {change_msg}")
                    stats["roles_added"] = stats["roles_added"] + 1
                    stats["changes"].append(f"✓ {change_msg}")

                elif not should_have_role and has_role:
                    # Remove role
                    logger.info(
                        f"Removing {competition_role.name} from {member.name} (ID: {member.id}, "
                        f"display: {member.display_name})"
                    )
                    await member.remove_roles(
                        competition_role,
                        reason=f"Role sync: no longer has {volunteer_role.name} in volunteer guild",
                    )
                    change_msg = f"Removed {competition_role.name} from {member.name} ({member.display_name})"
                    logger.info(f"✗ {change_msg}")
                    stats["roles_removed"] = stats["roles_removed"] + 1
                    stats["changes"].append(f"✗ {change_msg}")

                else:
                    # No action needed - member already in correct state
                    members_no_action += 1
                    logger.debug(f"No action needed for {member.name} (ID: {member.id}): already in correct state")

            except discord.errors.Forbidden as e:
                error_msg = f"Missing permissions to modify roles for {member.name} (ID: {member.id}): {e}"
                logger.exception(error_msg)
                stats["errors"] = stats["errors"] + 1
                stats["changes"].append(f"⚠ {error_msg}")
            except Exception as e:
                error_msg = f"Error syncing role for {member.name} (ID: {member.id}): {e}"
                logger.error(error_msg, exc_info=True)
                stats["errors"] = stats["errors"] + 1
                stats["changes"].append(f"⚠ {error_msg}")

        logger.info(f"Role pair sync complete: {volunteer_role.name} -> {competition_role.name}")
        logger.info(f"  Total members in competition guild: {len(competition_guild.members)}")
        logger.info(f"  Bot members skipped: {members_skipped_bot}")
        logger.info(f"  Human members checked: {members_checked}")
        logger.info(f"  Members already in correct state: {members_no_action}")
        logger.info(f"  Members with changes: {members_checked - members_no_action}")
        logger.info("-" * 80)


class AuthentikRoleSyncManager:
    """Manages role synchronization from Authentik groups to Discord competition guild.

    This syncs based on Authentik group membership (via UserGroups model) rather than
    Discord-to-Discord syncing. Users must have linked their Discord account via DiscordLink.
    """

    def __init__(self, bot: discord.Client) -> None:
        """Initialize Authentik role sync manager.

        Args:
            bot: Discord bot instance with access to competition guild
        """
        self.bot = bot
        self.competition_guild_id = settings.COMPETITION_GUILD_ID
        self.group_role_mapping = settings.GROUP_ROLE_MAPPING

    def _get_competition_guild(self) -> discord.Guild | None:
        """Get the competition guild object."""
        guild = self.bot.get_guild(self.competition_guild_id)
        if not guild:
            logger.error(f"Competition guild {self.competition_guild_id} not found")
        return guild

    async def sync_roles(
        self,
        dry_run: bool = False,
        progress_callback: Callable[[int, int, str], Awaitable[None]] | None = None,
    ) -> RoleSyncStats:
        """Synchronize roles from Authentik groups to competition Discord guild.

        This uses the UserGroups model (populated from Authentik OIDC) and DiscordLink
        to determine which Discord users should have which roles.

        Args:
            dry_run: If True, only report what would be done without making changes
            progress_callback: Optional async callback(current, total, role_name) for progress updates

        Returns:
            dict with sync statistics: roles_added, roles_removed, errors, changes
        """
        competition_guild = self._get_competition_guild()
        if not competition_guild:
            return {"roles_added": 0, "roles_removed": 0, "errors": 1, "changes": []}

        stats: RoleSyncStats = {
            "roles_added": 0,
            "roles_removed": 0,
            "errors": 0,
            "changes": [],
        }

        mode = "DRY RUN" if dry_run else "LIVE"
        logger.info("=" * 80)
        logger.info(f"AUTHENTIK ROLE SYNC STARTED [{mode}]")
        logger.info(f"Competition Guild: {competition_guild.name} (ID: {competition_guild.id})")
        logger.info(f"Group->Role Mappings: {len(self.group_role_mapping)} configured")
        for group_name, role_id in self.group_role_mapping.items():
            logger.info(f"  - {group_name} -> {role_id}")
        logger.info("=" * 80)

        # Chunk competition guild once at the start to get all members
        cached_member_count = len(competition_guild.members)
        logger.info(
            f"Fetching all members from competition guild "
            f"(currently have {cached_member_count} cached, chunked={competition_guild.chunked})..."
        )
        if not competition_guild.chunked:
            chunk_start = time.time()
            try:
                await asyncio.wait_for(competition_guild.chunk(), timeout=30.0)
                chunk_duration = time.time() - chunk_start
                logger.info(f"Guild chunk completed in {chunk_duration:.2f}s")
            except TimeoutError:
                chunk_duration = time.time() - chunk_start
                logger.warning(
                    f"Guild chunk timed out after {chunk_duration:.2f}s, "
                    f"using cached members ({len(competition_guild.members)} available)"
                )
        else:
            logger.info("Guild already chunked, skipping chunk request")
        logger.info(f"Competition guild has {len(competition_guild.members)} total members")

        # Get all Authentik group memberships and Discord links from database
        @sync_to_async
        def get_authentik_data() -> dict[str, set[int]]:
            """Get mapping of Authentik group name -> set of Discord IDs."""
            from core.models import UserGroups
            from team.models import DiscordLink

            group_to_discord_ids: dict[str, set[int]] = {group_name: set() for group_name in self.group_role_mapping}

            # Get all active Discord links with their users
            discord_links = DiscordLink.objects.filter(is_active=True).select_related("user")

            for link in discord_links:
                try:
                    user_groups = UserGroups.objects.get(user=link.user)
                    for group_name in self.group_role_mapping:
                        if group_name in user_groups.groups:
                            group_to_discord_ids[group_name].add(link.discord_id)
                except UserGroups.DoesNotExist:
                    continue

            return group_to_discord_ids

        group_to_discord_ids = await get_authentik_data()

        for group_name, discord_ids in group_to_discord_ids.items():
            logger.info(f"  {group_name}: {len(discord_ids)} linked Discord users")

        # Process each group->role mapping
        total_mappings = len(self.group_role_mapping)
        for idx, (group_name, role_id) in enumerate(self.group_role_mapping.items(), start=1):
            competition_role = competition_guild.get_role(role_id)
            role_name = competition_role.name if competition_role else f"Role {role_id}"

            # Report progress via callback if provided
            if progress_callback:
                await progress_callback(idx, total_mappings, role_name)

            try:
                await self._sync_authentik_group(
                    competition_guild,
                    group_name,
                    role_id,
                    group_to_discord_ids[group_name],
                    stats,
                    dry_run,
                )
            except Exception as e:
                logger.error(
                    f"Error syncing group {group_name} -> role {role_id}: {e}",
                    exc_info=True,
                )
                stats["errors"] = stats["errors"] + 1

        logger.info("=" * 80)
        logger.info(f"AUTHENTIK ROLE SYNC COMPLETE [{mode}]")
        logger.info(f"Roles Added: {stats['roles_added']}")
        logger.info(f"Roles Removed: {stats['roles_removed']}")
        logger.info(f"Errors: {stats['errors']}")
        changes = stats.get("changes", [])
        if isinstance(changes, list):
            logger.info(f"Total Changes: {len(changes)}")
        logger.info("=" * 80)
        return stats

    async def _sync_authentik_group(
        self,
        competition_guild: discord.Guild,
        group_name: str,
        role_id: int,
        should_have_role_discord_ids: set[int],
        stats: RoleSyncStats,
        dry_run: bool,
    ) -> None:
        """Sync a single Authentik group to Discord role.

        Args:
            competition_guild: Target guild where roles should be synced
            group_name: Authentik group name (for logging)
            role_id: Discord role ID to sync
            should_have_role_discord_ids: Set of Discord user IDs who should have this role
            stats: Statistics dict to update
            dry_run: If True, only report what would be done
        """
        competition_role = competition_guild.get_role(role_id)

        if not competition_role:
            logger.warning(f"Competition role {role_id} not found in {competition_guild.name}")
            return

        logger.info("-" * 80)
        logger.info(
            f"Syncing: {group_name} (Authentik) -> {competition_role.name} (ID: {role_id}, {competition_guild.name})"
        )
        logger.info(f"Users in Authentik group with linked Discord: {len(should_have_role_discord_ids)}")

        members_checked = 0
        members_skipped_bot = 0
        members_no_action = 0
        mode_prefix = "[DRY RUN] " if dry_run else ""

        for member in competition_guild.members:
            if member.bot:
                members_skipped_bot += 1
                continue

            members_checked += 1

            try:
                should_have_role = member.id in should_have_role_discord_ids
                has_role = competition_role in member.roles

                if should_have_role and not has_role:
                    # Add role
                    change_msg = f"Added {competition_role.name} to {member.name} ({member.display_name})"
                    if dry_run:
                        logger.info(f"{mode_prefix}Would add {competition_role.name} to {member.name}")
                        stats["changes"].append(f"[DRY RUN] ✓ {change_msg}")
                    else:
                        await member.add_roles(
                            competition_role,
                            reason=f"Authentik sync: member of {group_name}",
                        )
                        logger.info(f"✓ {change_msg}")
                        stats["changes"].append(f"✓ {change_msg}")
                    stats["roles_added"] = stats["roles_added"] + 1

                elif not should_have_role and has_role:
                    # Remove role
                    change_msg = f"Removed {competition_role.name} from {member.name} ({member.display_name})"
                    if dry_run:
                        logger.info(f"{mode_prefix}Would remove {competition_role.name} from {member.name}")
                        stats["changes"].append(f"[DRY RUN] ✗ {change_msg}")
                    else:
                        await member.remove_roles(
                            competition_role,
                            reason=f"Authentik sync: not member of {group_name}",
                        )
                        logger.info(f"✗ {change_msg}")
                        stats["changes"].append(f"✗ {change_msg}")
                    stats["roles_removed"] = stats["roles_removed"] + 1

                else:
                    members_no_action += 1

            except discord.errors.Forbidden as e:
                error_msg = f"Missing permissions to modify roles for {member.name} (ID: {member.id}): {e}"
                logger.exception(error_msg)
                stats["errors"] = stats["errors"] + 1
                stats["changes"].append(f"⚠ {error_msg}")
            except Exception as e:
                error_msg = f"Error syncing role for {member.name} (ID: {member.id}): {e}"
                logger.error(error_msg, exc_info=True)
                stats["errors"] = stats["errors"] + 1
                stats["changes"].append(f"⚠ {error_msg}")

        logger.info(f"Group sync complete: {group_name} -> {competition_role.name}")
        logger.info(f"  Total members in guild: {len(competition_guild.members)}")
        logger.info(f"  Bot members skipped: {members_skipped_bot}")
        logger.info(f"  Human members checked: {members_checked}")
        logger.info(f"  Members already in correct state: {members_no_action}")
        logger.info(f"  Members with changes: {members_checked - members_no_action}")
        logger.info("-" * 80)
