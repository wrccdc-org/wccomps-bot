"""Discord task queue processor for rate limit resilience."""

import logging
import asyncio
from typing import Optional
from datetime import timedelta
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from core.models import DiscordTask
from team.models import Team
from ticketing.models import Ticket, TicketComment
from bot.discord_manager import DiscordManager
from asgiref.sync import sync_to_async
import discord

logger = logging.getLogger(__name__)


class DiscordQueueProcessor:
    """Process Discord tasks from database queue using async tasks."""

    def __init__(self, bot: discord.Client) -> None:
        self.bot = bot
        self.discord_manager: Optional[DiscordManager] = None
        self.running = False
        self.task: Optional[asyncio.Task[None]] = None

    def start(self) -> None:
        """Start the queue processor as an async task."""
        import os

        self.running = True

        # Initialize discord manager with the configured guild
        guild_id = int(os.environ.get("DISCORD_GUILD_ID", 0))
        if guild_id:
            guild = self.bot.get_guild(guild_id)
            if guild:
                self.discord_manager = DiscordManager(guild, self.bot)
            else:
                logger.error(f"Could not find configured guild {guild_id}")
        elif self.bot.guilds:
            # Fallback to first guild if DISCORD_GUILD_ID not set
            guild = self.bot.guilds[0]
            self.discord_manager = DiscordManager(guild, self.bot)

        # Start processing task
        self.task = asyncio.create_task(self._process_loop())
        logger.info("Discord queue processor started")

    def stop(self) -> None:
        """Stop the queue processor."""
        self.running = False
        if self.task:
            self.task.cancel()
        logger.info("Discord queue processor stopped")

    async def _process_loop(self) -> None:
        """Main processing loop (runs as async task)."""
        while self.running:
            try:
                await self._process_pending_tasks()
            except Exception as e:
                logger.error(f"Error in queue processor: {e}")

            await asyncio.sleep(2)  # Poll every 2 seconds

    async def _process_pending_tasks(self) -> None:
        """Process pending tasks from the queue."""

        # Get pending tasks that are ready to process (using sync_to_async)
        @sync_to_async
        def get_pending_tasks() -> list[DiscordTask]:
            now = timezone.now()
            return list(
                DiscordTask.objects.filter(status="pending")
                .filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
                .order_by("created_at")[:10]
            )

        tasks = await get_pending_tasks()

        for task in tasks:
            await self._process_task(task)

    async def _process_task(self, task: DiscordTask) -> None:
        """Process a single task."""

        # Mark as processing
        @sync_to_async
        def mark_processing() -> None:
            with transaction.atomic():
                task.status = "processing"
                task.save()

        await mark_processing()

        try:
            # Execute task based on type
            if task.task_type == "assign_role":
                await self._handle_assign_role(task)
            elif task.task_type == "assign_group_roles":
                await self._handle_assign_group_roles(task)
            elif task.task_type == "remove_role":
                await self._handle_remove_role(task)
            elif task.task_type == "setup_team_infrastructure":
                await self._handle_setup_team_infrastructure(task)
            elif task.task_type == "log_to_channel":
                await self._handle_log_to_channel(task)
            elif task.task_type == "ticket_created_web":
                await self._handle_ticket_created_web(task)
            elif task.task_type == "post_comment":
                await self._handle_post_comment(task)
            elif task.task_type == "add_user_to_thread":
                await self._handle_add_user_to_thread(task)
            else:
                logger.warning(f"Unknown task type: {task.task_type}")
                await sync_to_async(lambda: setattr(task, "status", "failed"))()
                await sync_to_async(
                    lambda: setattr(
                        task, "error_message", f"Unknown task type: {task.task_type}"
                    )
                )()
                await sync_to_async(task.save)()
                return

            # Mark as completed
            @sync_to_async
            def mark_completed() -> None:
                task.status = "completed"
                task.completed_at = timezone.now()
                task.save()

            await mark_completed()
            logger.info(f"Completed task {task.id}: {task.task_type}")

        except discord.errors.RateLimited as rate_limit_error:
            # Handle rate limiting
            @sync_to_async
            def handle_rate_limit(error: discord.errors.RateLimited) -> float:
                retry_after = error.retry_after
                task.retry_count += 1
                task.next_retry_at = timezone.now() + timedelta(seconds=retry_after)
                task.status = "pending"
                task.error_message = f"Rate limited, retry after {retry_after}s"
                task.save()
                return retry_after

            retry_after = await handle_rate_limit(rate_limit_error)
            logger.warning(f"Task {task.id} rate limited, retrying in {retry_after}s")

        except Exception as error:
            # Handle other errors
            @sync_to_async
            def handle_error(exc: Exception) -> tuple[str, int]:
                task.retry_count += 1
                task.error_message = str(exc)

                if task.retry_count >= task.max_retries:
                    task.status = "failed"
                    task.save()
                    return "failed", task.max_retries
                else:
                    # Exponential backoff
                    backoff_seconds = min(2**task.retry_count, 300)  # Max 5 minutes
                    task.next_retry_at = timezone.now() + timedelta(
                        seconds=backoff_seconds
                    )
                    task.status = "pending"
                    task.save()
                    return "retry", backoff_seconds

            result, value = await handle_error(error)

            if result == "failed":
                logger.error(f"Task {task.id} failed after {value} retries: {error}")
                # Alert to ops channel
                try:
                    from bot.utils import log_to_ops_channel

                    await log_to_ops_channel(
                        self.bot,
                        f"Task {task.id} ({task.task_type}) failed after {value} retries: {error}",
                    )
                except Exception as log_error:
                    logger.error(f"Failed to log error to ops channel: {log_error}")
            else:
                logger.warning(
                    f"Task {task.id} failed (attempt {task.retry_count}), retrying in {value}s"
                )

    async def _handle_assign_role(self, task: DiscordTask) -> None:
        """Handle assign_role task."""
        if not self.discord_manager:
            raise Exception("Discord manager not initialized")

        discord_id = task.payload.get("discord_id")
        team_number = task.payload.get("team_number")

        if not discord_id or not team_number:
            raise ValueError("Missing discord_id or team_number in payload")

        guild = self.discord_manager.guild
        member = guild.get_member(discord_id)

        # If not in cache, try to fetch from API
        if not member:
            try:
                member = await guild.fetch_member(discord_id)
            except discord.NotFound:
                # Member is not in the guild
                try:
                    user = await self.bot.fetch_user(discord_id)
                    username = f"{user.name} ({discord_id})"
                except Exception:
                    username = str(discord_id)

                logger.warning(
                    f"Member {username} not found in guild, skipping role assignment. "
                    f"Role will be assigned when they join the server."
                )
                return
            except Exception as e:
                logger.error(f"Failed to fetch member {discord_id}: {e}")
                raise

        # Set up team infrastructure if needed
        @sync_to_async
        def get_team() -> Team:
            return Team.objects.get(team_number=team_number)

        team = await get_team()
        if not team.discord_role_id or not team.discord_category_id:
            logger.info(f"Setting up infrastructure for team {team_number}")
            await self.discord_manager.setup_team_infrastructure(team_number)

        # Assign role
        success = await self.discord_manager.assign_team_role(member, team_number)
        if not success:
            raise Exception(f"Failed to assign role to {member}")

        logger.info(f"Assigned team {team_number} role to {member}")

    async def _handle_assign_group_roles(self, task: DiscordTask) -> None:
        """Handle assign_group_roles task."""
        if not self.discord_manager:
            raise Exception("Discord manager not initialized")

        discord_id = task.payload.get("discord_id")
        authentik_groups = task.payload.get("authentik_groups", [])

        if not discord_id:
            raise ValueError("Missing discord_id in payload")

        guild = self.discord_manager.guild
        member = guild.get_member(discord_id)

        # If not in cache, try to fetch from API
        if not member:
            try:
                member = await guild.fetch_member(discord_id)
            except discord.NotFound:
                logger.warning(
                    f"Member {discord_id} not found in guild, skipping group role assignment"
                )
                return
            except Exception as e:
                logger.error(f"Failed to fetch member {discord_id}: {e}")
                raise

        # Assign group-based roles
        success = await self.discord_manager.assign_group_roles(
            member, authentik_groups
        )
        if not success:
            raise Exception(f"Failed to assign group roles to {member}")

        logger.info(f"Assigned group roles to {member}")

    async def _handle_remove_role(self, task: DiscordTask) -> None:
        """Handle remove_role task."""
        if not self.discord_manager:
            raise Exception("Discord manager not initialized")

        discord_id = task.payload.get("discord_id")
        team_number = task.payload.get("team_number")

        if not discord_id or not team_number:
            raise ValueError("Missing discord_id or team_number in payload")

        guild = self.discord_manager.guild
        member = guild.get_member(discord_id)

        # If not in cache, try to fetch from API
        if not member:
            try:
                member = await guild.fetch_member(discord_id)
            except discord.NotFound:
                logger.warning(
                    f"Member {discord_id} not in guild, skipping role removal"
                )
                return
            except Exception as e:
                logger.error(f"Failed to fetch member {discord_id}: {e}")
                raise

        success = await self.discord_manager.remove_team_role(member, team_number)
        if not success:
            raise Exception(f"Failed to remove role from {member}")

        logger.info(f"Removed team {team_number} role from {member}")

    async def _handle_setup_team_infrastructure(self, task: DiscordTask) -> None:
        """Handle setup_team_infrastructure task."""
        if not self.discord_manager:
            raise Exception("Discord manager not initialized")

        team_number = task.payload.get("team_number")
        if not team_number:
            raise ValueError("Missing team_number in payload")

        role, category = await self.discord_manager.setup_team_infrastructure(
            team_number
        )
        if not role or not category:
            raise Exception(f"Failed to setup infrastructure for team {team_number}")

        logger.info(f"Set up infrastructure for team {team_number}")

    async def _handle_log_to_channel(self, task: DiscordTask) -> None:
        """Handle log_to_channel task."""
        message = task.payload.get("message")
        if not message:
            raise ValueError("Missing message in payload")

        from bot.utils import log_to_ops_channel

        await log_to_ops_channel(self.bot, message)

    async def _handle_ticket_created_web(self, task: DiscordTask) -> None:
        """Handle ticket creation from web UI - create thread and post to dashboard."""
        from bot.ticket_dashboard import post_ticket_to_dashboard

        ticket_id = task.payload.get("ticket_id")
        if not ticket_id:
            raise ValueError("Missing ticket_id in payload")

        @sync_to_async
        def get_ticket() -> Ticket:
            return Ticket.objects.select_related("team").get(id=ticket_id)

        ticket = await get_ticket()

        # Check if thread already exists (from previous retry)
        if ticket.discord_thread_id:
            logger.info(
                f"Thread already exists for ticket {ticket.ticket_number}, updating dashboard"
            )
            # Still trigger dashboard update
            await post_ticket_to_dashboard(self.bot, ticket)
            return

        # Try to create thread in team's category
        if ticket.team.discord_category_id:
            try:
                category = self.bot.get_channel(ticket.team.discord_category_id)
                if not category:
                    logger.warning(
                        f"Category {ticket.team.discord_category_id} not found for team {ticket.team.team_name}"
                    )
                elif isinstance(category, discord.CategoryChannel):
                    # Find the team's text channel within the category
                    chat_channel = None
                    for channel in category.channels:
                        if (
                            isinstance(channel, discord.TextChannel)
                            and "chat" in channel.name.lower()
                        ):
                            chat_channel = channel
                            break

                    if not chat_channel:
                        logger.warning(
                            f"No text channel found in category {category.name}"
                        )
                        raise Exception("No text channel found in team category")

                    # Create thread in the team's text channel
                    thread = await chat_channel.create_thread(
                        name=f"{ticket.ticket_number} - Team {ticket.team.team_number:02d} - {ticket.title[:60]}",
                        auto_archive_duration=10080,  # 7 days
                    )

                    # Store thread ID
                    @sync_to_async
                    def save_thread_id() -> None:
                        ticket.discord_thread_id = thread.id
                        ticket.discord_channel_id = category.id
                        ticket.save()

                    await save_thread_id()

                    # Add all linked team members to thread
                    from bot.utils import get_team_member_discord_ids

                    team_member_ids = await get_team_member_discord_ids(ticket.team)
                    for member_id in team_member_ids:
                        try:
                            member = self.bot.get_user(member_id)
                            if member:
                                await thread.add_user(member)
                        except Exception as e:
                            logger.warning(
                                f"Failed to add member {member_id} to thread: {e}"
                            )

                    # Send initial message in thread with action buttons
                    from bot.ticket_dashboard import (
                        format_ticket_embed,
                        TicketActionView,
                    )

                    embed = format_ticket_embed(ticket)
                    view = TicketActionView(ticket.id)

                    message = await thread.send(
                        f"**Ticket #{ticket.ticket_number}** - Use buttons below to manage this ticket.",
                        embed=embed,
                        view=view,
                    )

                    # Pin the ticket message to the thread
                    try:
                        await message.pin()
                    except Exception as pin_error:
                        logger.warning(
                            f"Failed to pin ticket message in thread {thread.id}: {pin_error}"
                        )

                    logger.info(
                        f"Created thread {thread.id} for ticket #{ticket.ticket_number} from web"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to create thread for ticket {ticket.ticket_number}: {e}"
                )
        else:
            logger.warning(
                f"Team {ticket.team.team_name} has no category, ticket will appear in dashboard without thread"
            )

        # Always update dashboard, even if thread creation failed
        await post_ticket_to_dashboard(self.bot, ticket)

    async def _handle_post_comment(self, task: DiscordTask) -> None:
        """Handle posting a comment from web to Discord thread."""
        ticket_id = task.payload.get("ticket_id")
        comment_id = task.payload.get("comment_id")

        if not ticket_id or not comment_id:
            raise ValueError("Missing ticket_id or comment_id in payload")

        @sync_to_async
        def get_data() -> tuple[Ticket, TicketComment]:
            ticket = Ticket.objects.get(id=ticket_id)
            comment = TicketComment.objects.get(id=comment_id)
            return ticket, comment

        ticket, comment = await get_data()

        if not ticket.discord_thread_id:
            raise ValueError(f"Ticket #{ticket.id} has no Discord thread")

        # Get thread
        thread = self.bot.get_channel(ticket.discord_thread_id)
        if not thread:
            try:
                thread = await self.bot.fetch_channel(ticket.discord_thread_id)
            except Exception as e:
                raise ValueError(
                    f"Could not find thread {ticket.discord_thread_id}: {e}"
                )

        # Type guard for sendable channels
        if not isinstance(thread, (discord.TextChannel, discord.Thread)):
            raise ValueError(
                f"Channel {ticket.discord_thread_id} is not a text channel or thread"
            )

        # Format message
        message_content = f"**{comment.author_name}**\n{comment.comment_text}"

        # Post to thread
        message = await thread.send(message_content)

        # Store Discord message ID
        @sync_to_async
        def save_message_id() -> None:
            comment.discord_message_id = message.id
            comment.save()

        await save_message_id()

        logger.info(
            f"Posted comment {comment_id} to thread {thread.id} (message {message.id})"
        )

    async def _handle_add_user_to_thread(self, task: DiscordTask) -> None:
        """Add a user to a Discord thread."""
        discord_id = task.payload.get("discord_id")
        thread_id = task.payload.get("thread_id")

        if not discord_id or not thread_id:
            raise ValueError("Missing discord_id or thread_id in payload")

        # Get thread
        thread = self.bot.get_channel(thread_id)
        if not thread:
            try:
                thread = await self.bot.fetch_channel(thread_id)
            except Exception as e:
                raise ValueError(f"Could not find thread {thread_id}: {e}")

        # Type guard for threads
        if not isinstance(thread, discord.Thread):
            raise ValueError(f"Channel {thread_id} is not a thread")

        # Get user
        user = self.bot.get_user(discord_id)
        if not user:
            try:
                user = await self.bot.fetch_user(discord_id)
            except Exception as e:
                raise ValueError(f"Could not find user {discord_id}: {e}")

        # Add user to thread
        await thread.add_user(user)

        logger.info(f"Added user {discord_id} to thread {thread_id}")
