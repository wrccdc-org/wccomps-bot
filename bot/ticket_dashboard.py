"""Ticket dashboard management for #ticket-queue channel."""

from typing import Optional, Tuple, cast, Any
import discord
import logging
from django.utils import timezone
from ticketing.models import Ticket
from core.tickets_config import TICKET_CATEGORIES

logger = logging.getLogger(__name__)


def get_ticket_color(status: str) -> discord.Color:
    """Get embed color based on ticket status."""
    colors: dict[str, discord.Color] = {
        "open": discord.Color.red(),
        "claimed": discord.Color.orange(),
        "resolved": discord.Color.green(),
        "cancelled": discord.Color.dark_gray(),  # type: ignore[misc]
    }
    return colors.get(status, discord.Color.default())


def format_ticket_embed(ticket: Ticket) -> discord.Embed:
    """Format ticket as Discord embed."""
    cat_info = TICKET_CATEGORIES.get(ticket.category, {})

    embed = discord.Embed(
        title=f"Ticket {ticket.ticket_number}: {ticket.title}",
        description=ticket.description,
        color=get_ticket_color(ticket.status),
        timestamp=ticket.created_at,
    )

    # Team info
    embed.add_field(
        name="Team",
        value=f"{ticket.team.team_name} (#{ticket.team.team_number})",
        inline=True,
    )

    # Status
    status_display = ticket.status.replace("_", " ").title()
    embed.add_field(name="Status", value=status_display, inline=True)

    # Assigned to
    if ticket.assigned_to_discord_id:
        embed.add_field(
            name="Assigned To",
            value=f"<@{ticket.assigned_to_discord_id}> ({ticket.assigned_to_discord_username})",
            inline=False,
        )

    # Point impact
    points = cat_info.get("points", 0)
    if points > 0:
        if cat_info.get("variable_points", False):
            min_pts = cat_info.get("min_points", 0)
            max_pts = cat_info.get("max_points", 0)
            point_text = f"{min_pts}-{max_pts} points (variable)"
        else:
            point_text = f"{points} points"
        embed.add_field(name="Point Impact", value=point_text, inline=True)

    # Resolution info
    if ticket.resolved_at:
        embed.add_field(
            name="Resolved At",
            value=discord.utils.format_dt(ticket.resolved_at, style="R"),
            inline=True,
        )
        if ticket.resolution_notes:
            embed.add_field(
                name="Resolution Notes",
                value=ticket.resolution_notes[:1024],
                inline=False,
            )

    embed.set_footer(text=f"Category: {cat_info.get('name', ticket.category)}")

    return embed


async def post_ticket_to_dashboard(bot: Any, ticket: Ticket) -> None:
    """Trigger unified dashboard update for new ticket."""
    # Trigger unified dashboard update only (no individual messages)
    if hasattr(bot, "unified_dashboard") and bot.unified_dashboard:
        await bot.unified_dashboard.trigger_update()
        logger.info(f"Triggered dashboard update for new ticket {ticket.ticket_number}")


async def update_ticket_dashboard(bot: Any, ticket: Ticket) -> None:
    """Trigger unified dashboard update for ticket changes."""
    # Trigger unified dashboard update only (no individual messages)
    if hasattr(bot, "unified_dashboard") and bot.unified_dashboard:
        await bot.unified_dashboard.trigger_update()
        logger.debug(f"Triggered dashboard update for ticket {ticket.ticket_number}")


class TicketActionView(discord.ui.View):
    """Action buttons for ticket dashboard."""

    def __init__(self, ticket_id: int, thread_url: Optional[str] = None) -> None:
        super().__init__(timeout=None)
        self.ticket_id = ticket_id

        # Add thread link button if URL provided
        if thread_url:
            self.add_item(
                discord.ui.Button(
                    label="Go to Thread",
                    style=discord.ButtonStyle.link,
                    url=thread_url,
                    row=0,
                )
            )

    @discord.ui.button(
        label="Claim",
        style=discord.ButtonStyle.primary,
        custom_id="ticket_claim",
        row=1,
    )
    async def claim_button(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        """Claim a ticket."""
        from bot.permissions import can_support_tickets_async

        # Check permissions
        if not await can_support_tickets_async(interaction):
            await interaction.response.send_message(
                "You don't have permission to claim tickets. "
                "Contact an administrator if you need ticketing support access.",
                ephemeral=True,
            )
            return

        from django.db import transaction
        from ticketing.models import TicketHistory
        from asgiref.sync import sync_to_async

        # Use select_for_update to prevent race conditions
        @sync_to_async
        def claim_ticket_atomic() -> Tuple[Optional[Ticket], Optional[str]]:
            with transaction.atomic():
                ticket: Optional[Ticket] = (
                    Ticket.objects.select_for_update().filter(id=self.ticket_id).first()
                )

                if not ticket:
                    return None, "Ticket not found."

                if ticket.status != "open":
                    return None, f"This ticket is already {ticket.status}."

                # Update ticket
                ticket.status = "claimed"
                ticket.assigned_to_discord_id = interaction.user.id
                ticket.assigned_to_discord_username = str(interaction.user)
                ticket.assigned_at = timezone.now()
                ticket.save()

                # Add history
                TicketHistory.objects.create(
                    ticket=ticket,
                    action="claimed",
                    actor_username=str(interaction.user),
                    details={"assigned_to": str(interaction.user)},
                )

                return ticket, None

        ticket, error = await claim_ticket_atomic()
        if error or ticket is None:
            await interaction.response.send_message(
                error or "Failed to claim ticket.", ephemeral=True
            )
            return

        # Update dashboard (outside transaction)
        await update_ticket_dashboard(interaction.client, ticket)

        await interaction.response.send_message(
            f"You have claimed ticket {ticket.ticket_number}.",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Resolve",
        style=discord.ButtonStyle.success,
        custom_id="ticket_resolve",
        row=1,
    )
    async def resolve_button(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        """Show resolve modal with category dropdown and notes."""
        from bot.permissions import can_support_tickets_async

        # Check permissions
        if not await can_support_tickets_async(interaction):
            await interaction.response.send_message(
                "You don't have permission to resolve tickets. "
                "Contact an administrator if you need ticketing support access.",
                ephemeral=True,
            )
            return

        ticket = await Ticket.objects.filter(id=self.ticket_id).afirst()
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return

        if ticket.status == "resolved":
            await interaction.response.send_message(
                "This ticket is already resolved.", ephemeral=True
            )
            return

        # Show resolve modal
        modal = ResolveTicketModal(ticket)
        await interaction.response.send_modal(modal)

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.danger,
        custom_id="ticket_cancel",
        row=2,
    )
    async def cancel_button(
        self, interaction: discord.Interaction, button: discord.ui.Button[Any]
    ) -> None:
        """Cancel an unclaimed ticket (team members only)."""
        from team.models import DiscordLink
        from ticketing.models import TicketHistory
        from asgiref.sync import sync_to_async

        # Check if user is linked to a team
        @sync_to_async
        def get_team_link() -> Optional[DiscordLink]:
            return (
                DiscordLink.objects.filter(
                    discord_id=interaction.user.id, is_active=True
                )
                .select_related("team")
                .first()
            )

        link = await get_team_link()
        if not link or not link.team:
            await interaction.response.send_message(
                "You must be linked to a team to cancel tickets.", ephemeral=True
            )
            return

        # Get ticket
        ticket = (
            await Ticket.objects.select_related("team")
            .filter(id=self.ticket_id)
            .afirst()
        )
        if not ticket:
            await interaction.response.send_message("Ticket not found.", ephemeral=True)
            return

        # Verify ticket belongs to user's team
        if ticket.team.id != link.team.id:
            await interaction.response.send_message(
                "This ticket does not belong to your team.", ephemeral=True
            )
            return

        # Only allow cancellation if unclaimed
        if ticket.status != "open":
            await interaction.response.send_message(
                f"Cannot cancel this ticket. It is already {ticket.status}.\n"
                f"Claimed or in-progress tickets must be cancelled by an admin.",
                ephemeral=True,
            )
            return

        # Cancel ticket
        ticket.status = "cancelled"
        ticket.resolved_at = timezone.now()
        ticket.resolution_notes = f"Cancelled by {interaction.user}"
        await ticket.asave()

        # Create history entry
        await TicketHistory.objects.acreate(
            ticket=ticket,
            action="cancelled",
            actor_username=str(interaction.user),
            details={"reason": "Cancelled by team member (unclaimed)"},
        )

        # Update dashboard
        await update_ticket_dashboard(interaction.client, ticket)

        await interaction.response.send_message(
            f"Ticket {ticket.ticket_number} has been cancelled (no point penalty).",
            ephemeral=True,
        )


class ResolveTicketModal(discord.ui.Modal, title="Resolve Ticket"):
    """Modal for resolving a ticket."""

    def __init__(self, ticket: Ticket) -> None:
        super().__init__()
        self.ticket = ticket

        # Check if variable points category
        cat_info = TICKET_CATEGORIES.get(ticket.category, {})
        if cat_info.get("variable_points", False):
            min_pts = cat_info.get("min_points", 0)
            max_pts = cat_info.get("max_points", 0)
            self.points.placeholder = f"Enter points ({min_pts}-{max_pts})"
            self.points.required = True

    notes: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Resolution Notes",
        placeholder="Describe how the issue was resolved...",
        style=discord.TextStyle.paragraph,
        required=False,
        max_length=1000,
    )

    points: discord.ui.TextInput[Any] = discord.ui.TextInput(
        label="Points (for variable categories)",
        placeholder="Leave blank for fixed-point categories",
        required=False,
        max_length=5,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        """Handle modal submission."""
        from ticketing.models import TicketHistory
        from datetime import timedelta

        cat_info = TICKET_CATEGORIES.get(self.ticket.category, {})

        # Determine point penalty
        if cat_info.get("variable_points", False):
            if self.points.value.strip():
                try:
                    point_penalty = int(self.points.value.strip())
                    min_pts = cast(int, cat_info.get("min_points", 0))
                    max_pts = cast(int, cat_info.get("max_points", 0))
                    if point_penalty < min_pts or point_penalty > max_pts:
                        await interaction.response.send_message(
                            f"Point value must be between {min_pts} and {max_pts}.",
                            ephemeral=True,
                        )
                        return
                except ValueError:
                    await interaction.response.send_message(
                        "Invalid point value. Must be a number.", ephemeral=True
                    )
                    return
            else:
                await interaction.response.send_message(
                    f"This category requires a point value between {cat_info.get('min_points', 0)} and {cat_info.get('max_points', 0)}.",
                    ephemeral=True,
                )
                return
        else:
            point_penalty = cat_info.get("points", 0)

        # Update ticket
        self.ticket.status = "resolved"
        self.ticket.resolved_at = timezone.now()
        self.ticket.resolved_by_discord_id = interaction.user.id
        self.ticket.resolved_by_discord_username = str(interaction.user)
        self.ticket.resolution_notes = self.notes.value
        self.ticket.points_charged = point_penalty
        if not self.ticket.assigned_to_discord_id:
            self.ticket.assigned_to_discord_id = interaction.user.id
            self.ticket.assigned_to_discord_username = str(interaction.user)

        # Schedule thread archiving after 60 seconds
        if self.ticket.discord_thread_id:
            self.ticket.thread_archive_scheduled_at = timezone.now() + timedelta(
                seconds=60
            )

        await self.ticket.asave()

        # Create history entry
        await TicketHistory.objects.acreate(
            ticket=self.ticket,
            action="resolved",
            actor_username=str(interaction.user),
            details={
                "notes": self.notes.value,
                "point_penalty": point_penalty,
            },
        )

        # Update dashboard
        await update_ticket_dashboard(interaction.client, self.ticket)

        await interaction.response.send_message(
            f"Ticket {self.ticket.ticket_number} resolved with {point_penalty} point penalty.",
            ephemeral=True,
        )
