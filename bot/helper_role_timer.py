"""Student helper role management timer - Auto-assign and revoke invitational roles."""

import asyncio
import contextlib
import logging

import discord
from asgiref.sync import sync_to_async
from django.db.models import Q
from django.utils import timezone

from bot.utils import log_to_ops_channel

logger = logging.getLogger(__name__)


class HelperRoleTimer:
    """Background task to manage student helper role assignments."""

    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot
        self.task: asyncio.Task[None] | None = None
        self.running = False
        self.guild: discord.Guild | None = None

    def start(self) -> None:
        """Start the helper role timer task."""
        if not self.running:
            self.running = True
            self.task = asyncio.create_task(self._check_loop())
            logger.info("Helper role timer started")

    def stop(self) -> None:
        """Stop the helper role timer task."""
        self.running = False
        if self.task:
            self.task.cancel()
            logger.info("Helper role timer stopped")

    async def _check_loop(self) -> None:
        """Main loop to check helper role assignments."""
        while self.running:
            try:
                await self._check_helper_roles()
            except Exception as e:
                logger.exception(f"Error in helper role timer check: {e}")

            # Check every 5 minutes (less frequent than competition timer)
            await asyncio.sleep(300)

    async def _check_helper_roles(self) -> None:
        """Check and update student helper role assignments."""
        # Import here to avoid circular imports
        from competition.models import StudentHelper
        from django.conf import settings

        # Get guild
        if not self.guild:
            guild_id = getattr(settings, "DISCORD_GUILD_ID", None)
            if not guild_id:
                logger.warning("DISCORD_GUILD_ID not configured, skipping helper role check")
                return
            self.guild = self.bot.get_guild(int(guild_id))
            if not self.guild:
                logger.warning(f"Could not find guild {guild_id}")
                return

        @sync_to_async
        def get_helpers_to_process():  # type: ignore[no-untyped-def]
            """Get helpers that need activation or deactivation."""
            now = timezone.now()

            # Find pending helpers that should be activated
            # (start time has passed and status is still pending)
            to_activate = list(
                StudentHelper.objects.filter(
                    status="pending",
                )
                .select_related("person", "competition")
                .all()
            )

            # Filter in Python to handle custom vs competition times
            to_activate = [
                helper
                for helper in to_activate
                if helper.get_start_time() <= now <= helper.get_end_time()  # type: ignore[no-untyped-call]
            ]

            # Find active helpers that should be deactivated
            # (end time has passed)
            to_deactivate = list(
                StudentHelper.objects.filter(
                    status="active",
                )
                .select_related("person", "competition")
                .all()
            )

            # Filter in Python to handle custom vs competition times
            to_deactivate = [helper for helper in to_deactivate if not helper.should_be_active()]

            return {
                "activate": to_activate,
                "deactivate": to_deactivate,
            }

        try:
            helpers = await get_helpers_to_process()
            activated_count = 0
            deactivated_count = 0
            errors = []

            # Activate pending helpers
            for helper in helpers["activate"]:
                try:
                    success = await self._activate_helper(helper)
                    if success:
                        activated_count += 1
                    else:
                        errors.append(f"Failed to activate {helper.authentik_username}")
                except Exception as e:
                    logger.exception(f"Error activating helper {helper.authentik_username}: {e}")
                    errors.append(f"Error activating {helper.authentik_username}: {str(e)}")

            # Deactivate expired helpers
            for helper in helpers["deactivate"]:
                try:
                    success = await self._deactivate_helper(helper)
                    if success:
                        deactivated_count += 1
                    else:
                        errors.append(f"Failed to deactivate {helper.authentik_username}")
                except Exception as e:
                    logger.exception(f"Error deactivating helper {helper.authentik_username}: {e}")
                    errors.append(f"Error deactivating {helper.authentik_username}: {str(e)}")

            # Log summary if any changes were made
            if activated_count > 0 or deactivated_count > 0:
                msg = f"**Helper Role Update**\n\n"
                msg += f"✓ Activated: {activated_count}\n"
                msg += f"✓ Deactivated: {deactivated_count}\n"
                if errors:
                    msg += f"\n✗ **Errors:** {len(errors)}\n"
                    for error in errors[:5]:  # Limit to first 5 errors
                        msg += f"  • {error}\n"
                    if len(errors) > 5:
                        msg += f"  • ... and {len(errors) - 5} more\n"

                logger.info(f"Helper role update: {activated_count} activated, {deactivated_count} deactivated")
                await log_to_ops_channel(self.bot, msg)

        except Exception as e:
            logger.exception(f"Failed to process helper roles: {e}")
            with contextlib.suppress(Exception):
                await log_to_ops_channel(
                    self.bot,
                    f"**Error processing helper roles:** {e}",
                )

    async def _activate_helper(self, helper) -> bool:  # type: ignore[no-untyped-def]
        """
        Activate a helper by assigning Discord role.

        Args:
            helper: StudentHelper instance

        Returns:
            True if successful, False otherwise
        """
        if not self.guild:
            logger.warning("Guild not available, cannot activate helper")
            return False

        try:
            # Get member
            member = self.guild.get_member(helper.discord_id)
            if not member:
                logger.warning(f"Could not find member {helper.discord_id} ({helper.discord_username})")
                return False

            # Check if role already exists
            role = discord.utils.get(self.guild.roles, name=helper.discord_role_name)

            # Create role if it doesn't exist
            if not role:
                role = await self.guild.create_role(
                    name=helper.discord_role_name,
                    reason=f"Student helper role for {helper.competition.name}",
                )
                logger.info(f"Created new helper role: {helper.discord_role_name}")

            # Assign role to member
            await member.add_roles(role, reason=f"Student helper for {helper.competition.name}")

            # Update database
            @sync_to_async
            def save_activation() -> None:
                helper.activate(role.id)

            await save_activation()

            logger.info(f"Activated helper {helper.authentik_username} with role {helper.discord_role_name}")
            return True

        except discord.errors.Forbidden:
            logger.exception(f"No permission to assign role to {helper.discord_username}")
            return False
        except Exception as e:
            logger.exception(f"Error activating helper {helper.authentik_username}: {e}")
            return False

    async def _deactivate_helper(self, helper) -> bool:  # type: ignore[no-untyped-def]
        """
        Deactivate a helper by removing Discord role.

        Args:
            helper: StudentHelper instance

        Returns:
            True if successful, False otherwise
        """
        if not self.guild:
            logger.warning("Guild not available, cannot deactivate helper")
            return False

        try:
            # Get member
            member = self.guild.get_member(helper.discord_id)
            if not member:
                logger.warning(f"Could not find member {helper.discord_id} ({helper.discord_username})")
                # Still mark as deactivated in database
                @sync_to_async
                def save_deactivation_no_member() -> None:
                    helper.deactivate()

                await save_deactivation_no_member()
                return True

            # Get role
            role = None
            if helper.discord_role_id:
                role = self.guild.get_role(helper.discord_role_id)
            if not role:
                role = discord.utils.get(self.guild.roles, name=helper.discord_role_name)

            # Remove role from member
            if role and role in member.roles:
                await member.remove_roles(role, reason=f"Helper period ended for {helper.competition.name}")
                logger.info(f"Removed role {helper.discord_role_name} from {helper.discord_username}")

            # Update database
            @sync_to_async
            def save_deactivation() -> None:
                helper.deactivate()

            await save_deactivation()

            logger.info(f"Deactivated helper {helper.authentik_username}")
            return True

        except discord.errors.Forbidden:
            logger.exception(f"No permission to remove role from {helper.discord_username}")
            return False
        except Exception as e:
            logger.exception(f"Error deactivating helper {helper.authentik_username}: {e}")
            return False

    async def revoke_helper_role(self, helper_id: int, user_id: int, reason: str = "") -> bool:
        """
        Manually revoke a helper's role before expiration.

        Args:
            helper_id: StudentHelper ID
            user_id: Django User ID performing the revocation
            reason: Reason for revocation

        Returns:
            True if successful, False otherwise
        """
        from competition.models import StudentHelper
        from django.contrib.auth.models import User

        @sync_to_async
        def get_helper_and_user():  # type: ignore[no-untyped-def]
            try:
                helper = StudentHelper.objects.select_related("person", "competition").get(id=helper_id)
                user = User.objects.get(id=user_id)
                return helper, user
            except (StudentHelper.DoesNotExist, User.DoesNotExist):
                return None, None

        try:
            helper, user = await get_helper_and_user()
            if not helper or not user:
                logger.warning(f"Could not find helper {helper_id} or user {user_id}")
                return False

            # Remove Discord role first
            success = await self._deactivate_helper(helper)

            # Mark as revoked in database
            @sync_to_async
            def save_revocation() -> None:
                helper.revoke(user, reason)

            await save_revocation()

            logger.info(f"Revoked helper {helper.authentik_username} by {user.username}: {reason}")
            return success

        except Exception as e:
            logger.exception(f"Error revoking helper {helper_id}: {e}")
            return False
