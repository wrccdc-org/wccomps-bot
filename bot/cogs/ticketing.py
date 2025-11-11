"""Ticketing commands for team support."""

import discord
from discord import app_commands
from discord.ext import commands, tasks
import logging
from typing import Any
from django.utils import timezone
from team.models import DiscordLink
from ticketing.models import Ticket, TicketHistory, TicketAttachment, TicketComment
from core.tickets_config import TICKET_CATEGORIES
from bot.ticket_dashboard import post_ticket_to_dashboard

logger = logging.getLogger(__name__)


class TicketingCog(commands.Cog):
    """Commands for creating and managing tickets."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.archive_threads_task.start()

    async def cog_unload(self) -> None:
        """Clean up when cog is unloaded."""
        self.archive_threads_task.cancel()

    @tasks.loop(minutes=1)
    async def archive_threads_task(self) -> None:
        """Background task to archive resolved ticket threads after 60s grace period."""
        try:
            # Find tickets with threads scheduled for archiving
            now = timezone.now()
            tickets_to_archive = [
                ticket
                async for ticket in Ticket.objects.filter(
                    thread_archive_scheduled_at__lte=now,
                    discord_thread_id__isnull=False,
                    status__in=["resolved", "cancelled"],
                )
            ]

            for ticket in tickets_to_archive:
                try:
                    # Get thread
                    if ticket.discord_thread_id is None:
                        continue
                    thread = self.bot.get_channel(ticket.discord_thread_id)
                    if not thread:
                        # Thread not found, clear scheduled time
                        ticket.thread_archive_scheduled_at = None
                        await ticket.asave()
                        continue

                    # Archive thread
                    if isinstance(thread, discord.Thread):
                        await thread.edit(archived=True, locked=True)

                    # Clear scheduled time
                    ticket.thread_archive_scheduled_at = None
                    await ticket.asave()

                    # Log action
                    await TicketHistory.objects.acreate(
                        ticket=ticket,
                        action="thread_archived",
                        actor_discord_id=None,
                        actor_username="System",
                        details={"archived_at": str(now)},
                    )

                    logger.info(
                        f"Archived thread for ticket #{ticket.id} (60s grace period expired)"
                    )

                except Exception as e:
                    logger.error(
                        f"Failed to archive thread for ticket #{ticket.id}: {e}"
                    )
                    # Clear scheduled time on error to avoid retrying
                    ticket.thread_archive_scheduled_at = None
                    await ticket.asave()

        except Exception as e:
            logger.error(f"Error in archive_threads_task: {e}")

    @archive_threads_task.before_loop
    async def before_archive_threads_task(self) -> None:
        """Wait for bot to be ready before starting task."""
        await self.bot.wait_until_ready()

    @app_commands.command(
        name="ticket", description="[BLUE TEAM] Create a support ticket for your team"
    )
    @app_commands.describe(
        category="Type of support needed", description="Describe the issue or request"
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(
                name=f"{cat['display_name']} ({cat.get('points', 0)}pt)", value=cat_id
            )
            for cat_id, cat in TICKET_CATEGORIES.items()
            if cat.get("user_creatable", True)
        ]
    )
    async def create_ticket(
        self, interaction: discord.Interaction, category: str, description: str
    ) -> None:
        """Create a support ticket."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command must be used in a guild", ephemeral=True
            )
            return

        # Check if user is linked to a team
        link = await (
            DiscordLink.objects.filter(discord_id=interaction.user.id, is_active=True)
            .select_related("team")
            .afirst()
        )

        if not link:
            await interaction.response.send_message(
                "**This command is for Blue Team competitors only.**\n\n"
                "You must be linked to a competition team to create tickets.\n"
                "If you are a Blue Team member, use `/link` to connect your Discord account to your team.",
                ephemeral=True,
            )
            return

        # Check if user is actually on a team (not ops/admin)
        if not link.team:
            await interaction.response.send_message(
                "**This command is for Blue Team competitors only.**\n\n"
                "Your account is linked as an administrator or support member, not as a team competitor.\n"
                "If you need to create a ticket for a team, use `/tickets create` instead.",
                ephemeral=True,
            )
            return

        # Get category info
        cat_info = TICKET_CATEGORIES.get(category)
        if not cat_info:
            await interaction.response.send_message(
                "Invalid ticket category.", ephemeral=True
            )
            return

        # For box-reset, use description as hostname
        hostname = description if category == "box-reset" else ""

        # Generate ticket number
        latest_ticket = (
            await Ticket.objects.filter(team=link.team).order_by("-created_at").afirst()
        )
        if latest_ticket:
            # Extract sequence from last ticket (format: T001-XXX)
            try:
                last_seq = int(latest_ticket.ticket_number.split("-")[1])
                sequence = last_seq + 1
            except (IndexError, ValueError):
                sequence = 1
        else:
            sequence = 1

        ticket_number = f"T{link.team.team_number:03d}-{sequence:03d}"

        # Create ticket
        ticket = await Ticket.objects.acreate(
            ticket_number=ticket_number,
            team=link.team,
            category=category,
            title=cat_info["display_name"],
            description=description,
            hostname=hostname,
            status="open",
            points_charged=cat_info.get("points", 0),
        )

        # Create history entry
        await TicketHistory.objects.acreate(
            ticket=ticket,
            action="created",
            actor_username=str(interaction.user),
            details=f"Ticket created via Discord by {interaction.user}",
        )

        # Create thread in team's category
        if link.team.discord_category_id:
            try:
                team_category = interaction.guild.get_channel(
                    link.team.discord_category_id
                )
                if team_category and isinstance(team_category, discord.CategoryChannel):
                    # Find the team's text channel within the category
                    chat_channel = None
                    for channel in team_category.channels:
                        if (
                            isinstance(channel, discord.TextChannel)
                            and "chat" in channel.name.lower()
                        ):
                            chat_channel = channel
                            break

                    if not chat_channel:
                        logger.warning(
                            f"No text channel found in category {team_category.name}"
                        )
                        raise Exception("No text channel found in team category")

                    thread = await chat_channel.create_thread(
                        name=f"{ticket.ticket_number} - Team {link.team.team_number:02d} - {ticket.title[:60]}",
                        auto_archive_duration=10080,  # 7 days
                    )

                    # Store thread ID
                    from asgiref.sync import sync_to_async

                    @sync_to_async
                    def save_thread_id() -> None:
                        ticket.discord_thread_id = thread.id
                        ticket.discord_channel_id = team_category.id
                        ticket.save()

                    await save_thread_id()

                    # Add all linked team members to thread
                    from bot.utils import get_team_member_discord_ids

                    team_member_ids = await get_team_member_discord_ids(link.team)
                    for member_id in team_member_ids:
                        try:
                            member = interaction.guild.get_member(member_id)
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

                    embed_thread = format_ticket_embed(ticket)
                    view = TicketActionView(ticket.id)

                    await thread.send(
                        f"**Ticket #{ticket.ticket_number}** - Use buttons below to manage this ticket.",
                        embed=embed_thread,
                        view=view,
                    )

                    logger.info(
                        f"Created thread {thread.id} for ticket #{ticket.ticket_number}"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to create thread for ticket {ticket.ticket_number}: {e}"
                )

        # Post to dashboard
        try:
            await post_ticket_to_dashboard(self.bot, ticket)
        except Exception as e:
            logger.error(f"Failed to post ticket to dashboard: {e}")

        # Send confirmation
        embed = discord.Embed(
            title="✅ Ticket Created",
            description=f"Your {cat_info['display_name']} ticket has been created.",
            color=discord.Color.green(),
        )
        embed.add_field(name="Ticket Number", value=ticket.ticket_number, inline=True)
        embed.add_field(name="Status", value="Open", inline=True)
        embed.add_field(name="Team", value=link.team.team_name, inline=True)
        embed.add_field(
            name="Point Cost", value=f"{cat_info.get('points', 0)} points", inline=True
        )
        embed.add_field(name="Description", value=description, inline=False)

        # Add file attachment guidance
        embed.add_field(
            name="📎 Need to attach files?",
            value="Post screenshots, logs, or other files directly in the ticket thread.\n"
            "Find the thread in your team channels or #ticket-queue.",
            inline=False,
        )

        embed.set_footer(text="Volunteers will be notified in #ticket-queue")

        await interaction.response.send_message(embed=embed, ephemeral=True)
        logger.info(
            f"Ticket {ticket.ticket_number} created by {interaction.user} for {link.team.team_name}"
        )

    def _format_point_impact(self, cat_info: dict[str, Any]) -> str:
        """Format point impact message."""
        points = cat_info.get("points", 0)
        if points == 0:
            return "No point penalty"
        if cat_info.get("variable_points", False):
            min_pts = cat_info.get("min_points", 0)
            max_pts = cat_info.get("max_points", 0)
            return f"Point penalty: {min_pts}-{max_pts} points (set by volunteer)"
        return f"Point penalty: {points} points"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Handle messages in ticket threads (attachments and rate limiting)."""
        # Ignore bot messages
        if message.author.bot:
            return

        # Check if message is in a ticket thread
        if not isinstance(message.channel, discord.Thread):
            return

        # Get ticket by thread ID
        ticket = await Ticket.objects.filter(
            discord_thread_id=message.channel.id
        ).afirst()
        if not ticket:
            return

        # Check rate limit for comments
        from ticketing.models import CommentRateLimit
        from asgiref.sync import sync_to_async

        is_allowed, reason = await sync_to_async(CommentRateLimit.check_rate_limit)(
            ticket.id, message.author.id
        )

        if not is_allowed:
            try:
                await message.delete()
                await message.channel.send(
                    f"{message.author.mention} {reason}. Please slow down.",
                    delete_after=10,
                )
                logger.warning(
                    f"Rate limit exceeded for user {message.author.id} on ticket #{ticket.id}"
                )
                return
            except discord.Forbidden:
                logger.warning("Cannot delete message due to permissions")
                return

        # Record comment attempt for rate limiting
        await CommentRateLimit.objects.acreate(
            ticket=ticket, discord_id=message.author.id
        )

        # Save message as comment in database (for web interface visibility)
        if message.content:  # Only save if there's text content
            # Check if this message is already saved (prevent duplicates)
            existing = await TicketComment.objects.filter(
                discord_message_id=message.id
            ).afirst()

            if not existing:
                await TicketComment.objects.acreate(
                    ticket=ticket,
                    author_name=str(message.author),
                    author_discord_id=message.author.id,
                    comment_text=message.content,
                    discord_message_id=message.id,
                )
                logger.info(f"Saved Discord message as comment for ticket #{ticket.id}")

        # Process attachments
        if message.attachments:
            for attachment in message.attachments:
                # Limit file size to 10MB
                if attachment.size > 10 * 1024 * 1024:
                    await message.channel.send(
                        f"{message.author.mention} File `{attachment.filename}` is too large (max 10MB). Please use a file sharing service.",
                        delete_after=30,
                    )
                    continue

                try:
                    # Download file data
                    file_data = await attachment.read()

                    # Store in database
                    await TicketAttachment.objects.acreate(
                        ticket=ticket,
                        file_data=file_data,
                        filename=attachment.filename,
                        mime_type=attachment.content_type or "application/octet-stream",
                        uploaded_by=str(message.author),
                    )

                    logger.info(
                        f"Stored attachment {attachment.filename} for ticket #{ticket.id}"
                    )

                    # React to confirm upload
                    await message.add_reaction("📎")

                except Exception as e:
                    logger.error(
                        f"Failed to store attachment {attachment.filename}: {e}"
                    )
                    await message.channel.send(
                        f"{message.author.mention} Failed to store attachment `{attachment.filename}`. Please try again.",
                        delete_after=30,
                    )

    @commands.Cog.listener()
    async def on_message_edit(
        self, before: discord.Message, after: discord.Message
    ) -> None:
        """Sync message edits to TicketComment."""
        # Ignore bot messages
        if after.author.bot:
            return

        # Check if message is in a ticket thread
        if not isinstance(after.channel, discord.Thread):
            return

        # Get ticket by thread ID
        ticket = await Ticket.objects.filter(
            discord_thread_id=after.channel.id
        ).afirst()
        if not ticket:
            return

        # Find comment by message ID
        from ticketing.models import TicketComment

        comment = await TicketComment.objects.filter(
            ticket=ticket, discord_message_id=after.id
        ).afirst()

        if comment:
            # Update comment text
            comment.comment_text = after.content
            await comment.asave()

            logger.info(f"Synced edit to comment {comment.id} for ticket #{ticket.id}")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        """Mark TicketComment as deleted when Discord message is deleted."""
        # Ignore bot messages
        if message.author.bot:
            return

        # Check if message is in a ticket thread
        if not isinstance(message.channel, discord.Thread):
            return

        # Get ticket by thread ID
        ticket = await Ticket.objects.filter(
            discord_thread_id=message.channel.id
        ).afirst()
        if not ticket:
            return

        # Find comment by message ID
        from ticketing.models import TicketComment

        comment = await TicketComment.objects.filter(
            ticket=ticket, discord_message_id=message.id
        ).afirst()

        if comment:
            # Mark as deleted (soft delete)
            comment.comment_text = "[Message deleted]"
            await comment.asave()

            logger.info(
                f"Marked comment {comment.id} as deleted for ticket #{ticket.id}"
            )


async def post_comment_to_discord(
    bot: commands.Bot, comment: TicketComment
) -> discord.Message | None:
    """
    Post a TicketComment to the ticket's Discord thread.

    Args:
        bot: Discord bot instance
        comment: TicketComment model instance
    """

    # Get ticket and thread
    ticket = comment.ticket
    if not ticket.discord_thread_id:
        logger.warning(
            f"Cannot post comment to Discord: ticket #{ticket.id} has no thread"
        )
        return None

    # Get thread
    try:
        thread = bot.get_channel(ticket.discord_thread_id)
        if not thread:
            # Try fetching if not in cache
            thread = await bot.fetch_channel(ticket.discord_thread_id)

        if not thread:
            logger.error(
                f"Thread {ticket.discord_thread_id} not found for ticket #{ticket.id}"
            )
            return None
    except Exception as e:
        logger.error(f"Failed to get thread {ticket.discord_thread_id}: {e}")
        return None

    # Format comment message
    message_content = f"**{comment.author_name}**\n{comment.comment_text}"

    # Post to Discord
    try:
        if not isinstance(
            thread,
            (
                discord.Thread,
                discord.TextChannel,
                discord.VoiceChannel,
                discord.StageChannel,
            ),
        ):
            logger.error(
                f"Channel {ticket.discord_thread_id} is not a messageable channel"
            )
            return None
        message = await thread.send(message_content)

        # Store Discord message ID in comment
        comment.discord_message_id = message.id
        await comment.asave()

        logger.info(
            f"Posted comment to Discord thread {thread.id} (message {message.id})"
        )
        return message

    except Exception as e:
        logger.error(f"Failed to post comment to Discord: {e}")
        return None


async def setup(bot: commands.Bot) -> None:
    """Setup function to add cog to bot."""
    await bot.add_cog(TicketingCog(bot))
