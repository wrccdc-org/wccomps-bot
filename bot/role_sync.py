"""Role synchronization between volunteer and competition Discord guilds."""

import logging
from typing import Optional

import discord
from django.conf import settings

logger = logging.getLogger(__name__)


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

    def _get_guilds(self) -> tuple[Optional[discord.Guild], Optional[discord.Guild]]:
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

    async def sync_roles(self) -> dict[str, int | list[str]]:
        """Synchronize roles from volunteer guild to competition guild.

        This performs one-way sync: volunteer guild -> competition guild.
        - Users with roles in volunteer guild get them added in competition guild
        - Users without roles in volunteer guild get them removed from competition guild

        Returns:
            dict with sync statistics: roles_added, roles_removed, errors, changes
        """
        volunteer_guild, competition_guild = self._get_guilds()
        if not volunteer_guild or not competition_guild:
            return {"roles_added": 0, "roles_removed": 0, "errors": 1, "changes": []}

        stats: dict[str, int | list[str]] = {
            "roles_added": 0,
            "roles_removed": 0,
            "errors": 0,
            "changes": [],
        }

        logger.info("=" * 80)
        logger.info("ROLE SYNC STARTED")
        logger.info(
            f"Volunteer Guild: {volunteer_guild.name} (ID: {volunteer_guild.id})"
        )
        logger.info(
            f"Competition Guild: {competition_guild.name} (ID: {competition_guild.id})"
        )
        logger.info(f"Role Mappings: {len(self.role_mappings)} configured")
        for v_role_id, c_role_id in self.role_mappings.items():
            logger.info(f"  - {v_role_id} -> {c_role_id}")
        logger.info("=" * 80)

        # Process each role mapping
        for volunteer_role_id, competition_role_id in self.role_mappings.items():
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
                stats["errors"] = stats["errors"] + 1  # type: ignore

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
        stats: dict[str, int | list[str]],
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
            logger.warning(
                f"Volunteer role {volunteer_role_id} not found in {volunteer_guild.name}"
            )
            return

        if not competition_role:
            logger.warning(
                f"Competition role {competition_role_id} not found in {competition_guild.name}"
            )
            return

        logger.info("-" * 80)
        logger.info(
            f"Syncing: {volunteer_role.name} (ID: {volunteer_role_id}, {volunteer_guild.name}) -> "
            f"{competition_role.name} (ID: {competition_role_id}, {competition_guild.name})"
        )

        # Get members with role in volunteer guild
        volunteer_members_with_role = {m.id for m in volunteer_role.members}
        logger.info(
            f"Members with {volunteer_role.name} in volunteer guild: "
            f"{len(volunteer_members_with_role)}"
        )
        if volunteer_members_with_role:
            logger.debug(f"  Member IDs: {volunteer_members_with_role}")

        # Get all members in competition guild
        # We need to check all members because we may need to remove roles
        logger.info("Chunking competition guild to get all members...")
        await competition_guild.chunk()
        logger.info(
            f"Competition guild has {len(competition_guild.members)} total members"
        )

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
                    f"Checking {member.name} (ID: {member.id}): "
                    f"should_have={should_have_role}, has={has_role}"
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
                    stats["roles_added"] = stats["roles_added"] + 1  # type: ignore
                    stats["changes"].append(f"✓ {change_msg}")  # type: ignore

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
                    stats["roles_removed"] = stats["roles_removed"] + 1  # type: ignore
                    stats["changes"].append(f"✗ {change_msg}")  # type: ignore

                else:
                    # No action needed - member already in correct state
                    members_no_action += 1
                    logger.debug(
                        f"No action needed for {member.name} (ID: {member.id}): "
                        f"already in correct state"
                    )

            except discord.errors.Forbidden as e:
                error_msg = f"Missing permissions to modify roles for {member.name} (ID: {member.id}): {e}"
                logger.error(error_msg)
                stats["errors"] = stats["errors"] + 1  # type: ignore
                stats["changes"].append(f"⚠ {error_msg}")  # type: ignore
            except Exception as e:
                error_msg = (
                    f"Error syncing role for {member.name} (ID: {member.id}): {e}"
                )
                logger.error(error_msg, exc_info=True)
                stats["errors"] = stats["errors"] + 1  # type: ignore
                stats["changes"].append(f"⚠ {error_msg}")  # type: ignore

        logger.info(
            f"Role pair sync complete: {volunteer_role.name} -> {competition_role.name}"
        )
        logger.info(
            f"  Total members in competition guild: {len(competition_guild.members)}"
        )
        logger.info(f"  Bot members skipped: {members_skipped_bot}")
        logger.info(f"  Human members checked: {members_checked}")
        logger.info(f"  Members already in correct state: {members_no_action}")
        logger.info(f"  Members with changes: {members_checked - members_no_action}")
        logger.info("-" * 80)
