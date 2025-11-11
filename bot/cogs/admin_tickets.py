"""Admin commands for ticket management."""

import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import Optional, cast, Union
from django.utils import timezone
from datetime import timedelta
from core.models import DiscordTask
from ticketing.models import Ticket, TicketHistory
from core.tickets_config import TICKET_CATEGORIES
from bot.utils import (
    log_to_ops_channel,
    get_team_or_respond,
    get_team_member_discord_ids,
)
from bot.ticket_dashboard import (
    post_ticket_to_dashboard,
    update_ticket_dashboard,
    format_ticket_embed,
    TicketActionView,
)
from bot.permissions import check_ticketing_admin, check_ticketing_support

logger = logging.getLogger(__name__)


class UserOrIdTransformer(app_commands.Transformer):
    """Transform either a User mention or a Discord ID string into a User object."""

    async def transform(
        self, interaction: discord.Interaction, value: Union[discord.User, str]
    ) -> Optional[discord.User]:
        """
        Transform input into a discord.User.

        Accepts:
        - @mention (discord automatically converts to discord.User)
        - Raw Discord ID as string (we fetch the user)
        """
        # If the value is already a User, return it (from @mention)
        if isinstance(value, discord.User):
            return value

        # Try to parse as Discord ID
        try:
            user_id = int(value)
            user = await interaction.client.fetch_user(user_id)
            return user
        except (ValueError, discord.NotFound, discord.HTTPException):
            raise app_commands.AppCommandError(
                "Invalid user. Please provide a @mention or valid Discord ID."
            )


class AdminTicketsCog(commands.Cog):
    """Admin commands for ticket management."""

    # Create tickets command group as class attribute
    tickets_group = app_commands.Group(
        name="tickets", description="Ticket management commands"
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @tickets_group.command(
        name="create", description="[ADMIN] Create a ticket for a team"
    )
    @app_commands.describe(
        team_number="Team number (1-50)",
        category="Ticket category",
        description="Description of the issue",
    )
    @app_commands.choices(
        category=[
            app_commands.Choice(name=cat["display_name"], value=cat_id)
            for cat_id, cat in TICKET_CATEGORIES.items()
        ]
    )
    @app_commands.check(check_ticketing_admin)
    async def admin_ticket_create(
        self,
        interaction: discord.Interaction,
        team_number: int,
        category: str,
        description: str,
    ) -> None:
        """Create a ticket as admin."""
        if not interaction.guild:
            await interaction.response.send_message(
                "This command must be used in a guild", ephemeral=True
            )
            return

        team = await get_team_or_respond(interaction, team_number)
        if not team:
            return

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
            await Ticket.objects.filter(team=team).order_by("-created_at").afirst()
        )
        if latest_ticket:
            try:
                last_seq = int(latest_ticket.ticket_number.split("-")[1])
                sequence = last_seq + 1
            except (IndexError, ValueError):
                sequence = 1
        else:
            sequence = 1

        ticket_number = f"T{team.team_number:03d}-{sequence:03d}"

        # Create ticket
        ticket = await Ticket.objects.acreate(
            ticket_number=ticket_number,
            team=team,
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
            details=f"Ticket created by admin {interaction.user}",
        )

        # Create thread in team's category
        if team.discord_category_id:
            try:
                category_channel = (
                    interaction.guild.get_channel(team.discord_category_id)
                    if interaction.guild
                    else None
                )
                if category_channel and isinstance(
                    category_channel, discord.CategoryChannel
                ):
                    # Find the team's text channel within the category
                    chat_channel = None
                    for channel in category_channel.channels:
                        if (
                            isinstance(channel, discord.TextChannel)
                            and "chat" in channel.name.lower()
                        ):
                            chat_channel = channel
                            break

                    if not chat_channel:
                        logger.warning(
                            f"No text channel found in category {category_channel.name}"
                        )
                        raise Exception("No text channel found in team category")

                    thread = await chat_channel.create_thread(
                        name=f"{ticket.ticket_number} - Team {team.team_number:02d} - {ticket.title[:60]}",
                        auto_archive_duration=10080,  # 7 days
                    )

                    # Store thread ID
                    from asgiref.sync import sync_to_async

                    @sync_to_async
                    def save_thread_id() -> None:
                        ticket.discord_thread_id = thread.id
                        ticket.discord_channel_id = category_channel.id
                        ticket.save()

                    await save_thread_id()

                    # Add all linked team members to thread
                    team_member_ids = await get_team_member_discord_ids(team)
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
                    embed_thread = format_ticket_embed(ticket)
                    view = TicketActionView(ticket.id)

                    await thread.send(
                        f"**Ticket #{ticket.ticket_number}** - Use buttons below to manage this ticket.",
                        embed=embed_thread,
                        view=view,
                    )

                    logger.info(
                        f"Created thread {thread.id} for ticket #{ticket.ticket_number} (admin)"
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

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Admin Ticket Created: {ticket.ticket_number} - {cat_info['display_name']} for **{team.team_name}** by {interaction.user.mention}",
        )

        await interaction.response.send_message(
            f"Created ticket **{ticket.ticket_number}** for **{team.team_name}**\n"
            f"Category: {cat_info['display_name']}\n"
            f"Point cost: {cat_info.get('points', 0)} points",
            ephemeral=True,
        )

    @tickets_group.command(name="list", description="[ADMIN] List open tickets")
    @app_commands.describe(
        status="Filter by status", team_number="Filter by team number"
    )
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Open", value="open"),
            app_commands.Choice(name="Claimed", value="claimed"),
            app_commands.Choice(name="Resolved", value="resolved"),
            app_commands.Choice(name="All", value="all"),
        ]
    )
    @app_commands.check(check_ticketing_support)
    async def admin_ticket_list(
        self,
        interaction: discord.Interaction,
        status: str = "open",
        team_number: Optional[int] = None,
    ) -> None:
        """List tickets with optional filters."""

        # Build query
        query = Ticket.objects.select_related("team")
        if status != "all":
            query = query.filter(status=status)
        if team_number:
            query = query.filter(team__team_number=team_number)

        # Get total count first
        total_count = await query.acount()

        if total_count == 0:
            await interaction.response.send_message(
                "No tickets found matching criteria", ephemeral=True
            )
            return

        # Fetch tickets (limit to 25 due to Discord embed field limit)
        display_limit = 25
        tickets = [t async for t in query.order_by("-created_at")[:display_limit]]

        # Build title showing count
        if total_count > display_limit:
            title = f"Tickets ({status}) - Showing {display_limit} of {total_count}"
        else:
            title = f"Tickets ({status}) - {total_count} total"

        embed = discord.Embed(title=title, color=discord.Color.blue())

        for ticket in tickets:
            cat_info = TICKET_CATEGORIES.get(ticket.category, {})
            value = (
                f"Team: {ticket.team.team_name}\n"
                f"Category: {cat_info.get('display_name', ticket.category)}\n"
                f"Status: {ticket.status}\n"
                f"Created: {discord.utils.format_dt(ticket.created_at, style='R')}"
            )
            if ticket.assigned_to_discord_username:
                value += f"\nAssigned: {ticket.assigned_to_discord_username}"

            embed.add_field(
                name=f"{ticket.ticket_number}: {ticket.title}",
                value=value,
                inline=False,
            )

        if total_count > display_limit:
            embed.set_footer(text=f"Use web interface to see all {total_count} tickets")

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @tickets_group.command(
        name="resolve", description="[ADMIN] Resolve a ticket and apply points"
    )
    @app_commands.describe(
        ticket_number="Ticket number (e.g., T050-003)",
        notes="Resolution notes",
        points="Point adjustment (for variable point categories)",
    )
    @app_commands.check(check_ticketing_support)
    async def admin_ticket_resolve(
        self,
        interaction: discord.Interaction,
        ticket_number: str,
        notes: str = "",
        points: Optional[int] = None,
    ) -> None:
        """Resolve a ticket and apply point adjustments."""

        ticket = (
            await Ticket.objects.select_related("team")
            .filter(ticket_number=ticket_number)
            .afirst()
        )
        if not ticket:
            await interaction.response.send_message(
                f"Ticket {ticket_number} not found", ephemeral=True
            )
            return

        if ticket.status == "resolved":
            await interaction.response.send_message(
                f"Ticket {ticket.ticket_number} is already resolved", ephemeral=True
            )
            return

        cat_info = TICKET_CATEGORIES.get(ticket.category, {})

        # Determine point penalty
        if cat_info.get("variable_points", False):
            if points is None:
                min_pts = cat_info.get("min_points", 0)
                max_pts = cat_info.get("max_points", 0)
                await interaction.response.send_message(
                    f"This category requires a point value between {min_pts} and {max_pts}",
                    ephemeral=True,
                )
                return

            min_pts = cast(int, cat_info.get("min_points", 0))
            max_pts = cast(int, cat_info.get("max_points", 0))
            if points < min_pts or points > max_pts:
                await interaction.response.send_message(
                    f"Point value must be between {min_pts} and {max_pts}",
                    ephemeral=True,
                )
                return

            point_penalty = points
        else:
            point_penalty = cat_info.get("points", 0)

        # Update ticket
        ticket.status = "resolved"
        ticket.resolved_at = timezone.now()
        ticket.resolved_by_discord_id = interaction.user.id
        ticket.resolved_by_discord_username = str(interaction.user)
        ticket.resolution_notes = notes
        ticket.points_charged = point_penalty
        if not ticket.assigned_to_discord_id:
            ticket.assigned_to_discord_id = interaction.user.id
            ticket.assigned_to_discord_username = str(interaction.user)

        # Schedule thread archiving after 60 seconds
        if ticket.discord_thread_id:
            ticket.thread_archive_scheduled_at = timezone.now() + timedelta(seconds=60)

        await ticket.asave()

        # Create history entry
        await TicketHistory.objects.acreate(
            ticket=ticket,
            action="resolved",
            actor_username=str(interaction.user),
            details={"notes": notes, "point_penalty": point_penalty},
        )

        # Update dashboard
        try:
            await update_ticket_dashboard(self.bot, ticket)
        except Exception as e:
            logger.error(f"Failed to update dashboard: {e}")

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Ticket Resolved: {ticket.ticket_number} for **{ticket.team.team_name}** by {interaction.user.mention}\n"
            f"Point Penalty: {point_penalty} points",
        )

        await interaction.response.send_message(
            f"Resolved ticket {ticket.ticket_number}\n"
            f"Point Penalty: {point_penalty} points applied to {ticket.team.team_name}",
            ephemeral=True,
        )

    @tickets_group.command(
        name="cancel", description="[ADMIN] Cancel a ticket without applying points"
    )
    @app_commands.describe(
        ticket_number="Ticket number (e.g., T050-003)",
        reason="Reason for cancellation",
    )
    @app_commands.check(check_ticketing_admin)
    async def admin_ticket_cancel(
        self, interaction: discord.Interaction, ticket_number: str, reason: str = ""
    ) -> None:
        """Cancel a ticket without point penalty."""

        ticket = (
            await Ticket.objects.select_related("team")
            .filter(ticket_number=ticket_number)
            .afirst()
        )
        if not ticket:
            await interaction.response.send_message(
                f"Ticket {ticket_number} not found", ephemeral=True
            )
            return

        if ticket.status == "resolved" or ticket.status == "cancelled":
            await interaction.response.send_message(
                f"Ticket {ticket.ticket_number} is already {ticket.status}",
                ephemeral=True,
            )
            return

        # Update ticket
        ticket.status = "cancelled"
        ticket.resolved_at = timezone.now()
        ticket.resolution_notes = reason or "Cancelled by admin"
        if not ticket.assigned_to_discord_id:
            ticket.assigned_to_discord_id = interaction.user.id
            ticket.assigned_to_discord_username = str(interaction.user)

        # Schedule thread archiving if Discord thread exists
        if ticket.discord_thread_id:
            from datetime import timedelta

            ticket.thread_archive_scheduled_at = timezone.now() + timedelta(seconds=60)

        await ticket.asave()

        # Create history entry
        await TicketHistory.objects.acreate(
            ticket=ticket,
            action="cancelled",
            actor_username=str(interaction.user),
            details={"reason": reason},
        )

        # Update dashboard
        try:
            await update_ticket_dashboard(self.bot, ticket)
        except Exception as e:
            logger.error(f"Failed to update dashboard: {e}")

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Ticket Cancelled: {ticket.ticket_number} for **{ticket.team.team_name}** by {interaction.user.mention}\n"
            f"Reason: {reason or 'No reason provided'}",
        )

        await interaction.response.send_message(
            f"Cancelled ticket {ticket.ticket_number} (no point penalty applied)",
            ephemeral=True,
        )

    @tickets_group.command(
        name="reassign",
        description="[ADMIN] Reassign a ticket to a different volunteer",
    )
    @app_commands.describe(
        ticket_number="Ticket number (e.g., T050-003)",
        volunteer="Discord user (@mention or ID) to assign (leave empty to unassign)",
    )
    @app_commands.check(check_ticketing_admin)
    async def admin_ticket_reassign(
        self,
        interaction: discord.Interaction,
        ticket_number: str,
        volunteer: Optional[
            app_commands.Transform[discord.User, UserOrIdTransformer]
        ] = None,
    ) -> None:
        """Reassign a ticket to a different volunteer."""
        await interaction.response.defer(ephemeral=True)

        ticket = (
            await Ticket.objects.select_related("team")
            .filter(ticket_number=ticket_number)
            .afirst()
        )
        if not ticket:
            await interaction.followup.send(
                f"Ticket {ticket_number} not found", ephemeral=True
            )
            return

        if ticket.status in ["resolved", "cancelled"]:
            await interaction.followup.send(
                f"Cannot reassign {ticket.status} ticket", ephemeral=True
            )
            return

        old_assignee = ticket.assigned_to_discord_username or "Unassigned"

        if volunteer:
            ticket.assigned_to_discord_id = volunteer.id
            ticket.assigned_to_discord_username = str(volunteer)
            ticket.assigned_at = timezone.now()

            # Update status if open
            if ticket.status == "open":
                ticket.status = "claimed"

            new_assignee = str(volunteer)
        else:
            # Unassign
            ticket.assigned_to_discord_id = None
            ticket.assigned_to_discord_username = ""
            ticket.assigned_at = None
            ticket.status = "open"
            new_assignee = "Unassigned"

        await ticket.asave()

        # Create history
        await TicketHistory.objects.acreate(
            ticket=ticket,
            action="reassigned",
            actor_discord_id=interaction.user.id,
            actor_username=str(interaction.user),
            details={"old_assignee": old_assignee, "new_assignee": new_assignee},
        )

        # Update dashboard
        await DiscordTask.objects.acreate(task_type="update_dashboard", ticket=ticket)

        await interaction.followup.send(
            f"Ticket {ticket.ticket_number} reassigned\n• From: {old_assignee}\n• To: {new_assignee}",
            ephemeral=True,
        )

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Ticket reassigned by {interaction.user.mention}\n"
            f"• Ticket: {ticket.ticket_number} ({ticket.team.team_name})\n"
            f"• From: {old_assignee}\n"
            f"• To: {new_assignee}",
        )

    @tickets_group.command(
        name="reopen", description="[ADMIN] Reopen a resolved ticket"
    )
    @app_commands.describe(
        ticket_number="Ticket number (e.g., T050-003)", reason="Reason for reopening"
    )
    @app_commands.check(check_ticketing_admin)
    async def admin_ticket_reopen(
        self, interaction: discord.Interaction, ticket_number: str, reason: str
    ) -> None:
        """Reopen a resolved ticket."""
        await interaction.response.defer(ephemeral=True)

        ticket = (
            await Ticket.objects.select_related("team")
            .filter(ticket_number=ticket_number)
            .afirst()
        )
        if not ticket:
            await interaction.followup.send(
                f"Ticket {ticket_number} not found", ephemeral=True
            )
            return

        if ticket.status != "resolved":
            await interaction.followup.send(
                f"Cannot reopen - ticket is {ticket.status}", ephemeral=True
            )
            return

        # Reopen ticket (only change status and clear resolved timestamp)
        old_status = ticket.status
        ticket.status = "open"
        ticket.resolved_at = None
        await ticket.asave()

        # Create history
        await TicketHistory.objects.acreate(
            ticket=ticket,
            action="reopened",
            actor_discord_id=interaction.user.id,
            actor_username=str(interaction.user),
            details={
                "reason": reason,
                "old_status": old_status,
            },
        )

        # Update dashboard
        await DiscordTask.objects.acreate(task_type="update_dashboard", ticket=ticket)

        refund_msg = ""
        if ticket.points_charged > 0:
            refund_msg = f"\n• Refunded: {ticket.points_charged} points"

        await interaction.followup.send(
            f"Ticket {ticket.ticket_number} reopened\n• Reason: {reason}{refund_msg}",
            ephemeral=True,
        )

        # Log to ops
        await log_to_ops_channel(
            self.bot,
            f"Ticket reopened by {interaction.user.mention}\n"
            f"• Ticket: {ticket.ticket_number} ({ticket.team.team_name})\n"
            f"• Reason: {reason}{refund_msg}",
        )


async def setup(bot: commands.Bot) -> None:
    """Setup function to add cog to bot."""
    await bot.add_cog(AdminTicketsCog(bot))
