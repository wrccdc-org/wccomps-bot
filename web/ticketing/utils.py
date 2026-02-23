"""Ticketing utilities for atomic ticket creation and lifecycle management."""

from asgiref.sync import sync_to_async
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.tickets_config import get_category_config
from team.models import DiscordLink, Team
from ticketing.models import Ticket, TicketCategory, TicketHistory


def get_user_for_ticket(
    discord_id: int | None = None,
    user: User | None = None,
) -> User | None:
    """
    Get a User for ticket assignment/resolution.

    Args:
        discord_id: Discord user ID (looks up DiscordLink -> User)
        user: Django User object (preferred, returned directly)

    Returns:
        User object or None if not found.
    """
    if user:
        return user

    if discord_id:
        discord_link = DiscordLink.objects.filter(discord_id=discord_id, is_active=True).first()
        if discord_link and discord_link.user:
            return discord_link.user

    return None


def create_ticket_atomic(
    team: Team,
    category: TicketCategory,
    title: str,
    description: str = "",
    hostname: str = "",
    ip_address: str | None = None,
    service_name: str = "",
    actor_username: str = "system",
) -> Ticket:
    """
    Create a ticket with atomic ticket number generation.

    Uses transaction with select_for_update() to prevent race conditions.

    Args:
        team: Team to create ticket for
        category: TicketCategory instance
        title: Ticket title
        description: Ticket description
        hostname: Hostname (optional)
        ip_address: IP address (optional)
        service_name: Service name (optional)
        actor_username: Username of person creating ticket (for history)

    Returns:
        Created Ticket instance
    """
    with transaction.atomic():
        # Lock the team row to prevent concurrent ticket creation
        team = Team.objects.select_for_update().get(pk=team.pk)

        # Atomically increment counter
        team.ticket_counter = F("ticket_counter") + 1
        team.save(update_fields=["ticket_counter"])
        team.refresh_from_db()

        # Generate ticket number
        sequence = team.ticket_counter
        ticket_number = f"T{team.team_number:03d}-{sequence:03d}"

        # Create ticket
        ticket = Ticket.objects.create(
            ticket_number=ticket_number,
            team=team,
            category=category,
            title=title,
            description=description,
            hostname=hostname,
            ip_address=ip_address or None,
            service_name=service_name,
            status="open",
            points_charged=category.points,
        )

        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            action="created",
            details={"created_by": actor_username},
        )

    return ticket


async def acreate_ticket_atomic(
    team: Team,
    category: TicketCategory,
    title: str,
    description: str = "",
    hostname: str = "",
    ip_address: str | None = None,
    service_name: str = "",
    actor_username: str = "system",
) -> Ticket:
    """Async wrapper for create_ticket_atomic (Discord bot usage)."""
    return await sync_to_async(create_ticket_atomic)(
        team=team,
        category=category,
        title=title,
        description=description,
        hostname=hostname,
        ip_address=ip_address,
        service_name=service_name,
        actor_username=actor_username,
    )


def claim_ticket_atomic(
    ticket_id: int,
    actor_username: str,
    discord_id: int | None = None,
    discord_username: str | None = None,
    user: User | None = None,
) -> tuple[Ticket | None, str | None]:
    """
    Claim a ticket atomically with race condition protection.

    Args:
        ticket_id: ID of ticket to claim
        actor_username: Username for history (e.g., "discord:user" or "web:user")
        discord_id: Discord user ID (optional, used to look up User via DiscordLink)
        discord_username: Discord username (optional, for history only)
        user: Django User object (preferred)

    Returns:
        Tuple of (ticket, error_message). If error, ticket is None.
    """
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(id=ticket_id).first()

        if not ticket:
            return None, "Ticket not found."

        if ticket.status != "open":
            return None, f"This ticket is already {ticket.status}."

        assignee = get_user_for_ticket(discord_id=discord_id, user=user)

        if not assignee:
            return None, "Could not find a valid user to assign."

        # Update ticket
        ticket.status = "claimed"
        ticket.assigned_to = assignee
        ticket.assigned_at = timezone.now()
        ticket.save()

        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            action="claimed",
            actor=assignee,
            details={
                "claimed_by": actor_username,
                "discord_username": discord_username,
                "authentik_username": assignee.username,
            },
        )

        return ticket, None


async def aclaim_ticket_atomic(
    ticket_id: int,
    actor_username: str,
    discord_id: int | None = None,
    discord_username: str | None = None,
    user: User | None = None,
) -> tuple[Ticket | None, str | None]:
    """Async wrapper for claim_ticket_atomic."""
    return await sync_to_async(claim_ticket_atomic)(
        ticket_id=ticket_id,
        actor_username=actor_username,
        discord_id=discord_id,
        discord_username=discord_username,
        user=user,
    )


def resolve_ticket_atomic(
    ticket_id: int,
    actor_username: str,
    resolution_notes: str = "",
    points_override: int | None = None,
    discord_id: int | None = None,
    discord_username: str | None = None,
    user: User | None = None,
) -> tuple[Ticket | None, str | None]:
    """
    Resolve a ticket atomically.

    Args:
        ticket_id: ID of ticket to resolve
        actor_username: Username for history (e.g., "discord:user" or "web:user")
        resolution_notes: Notes describing resolution
        points_override: Override points for variable-point categories
        discord_id: Discord user ID (optional, used to look up User via DiscordLink)
        discord_username: Discord username (optional, for history only)
        user: Django User object (preferred)

    Returns:
        Tuple of (ticket, error_message). If error, ticket is None.
    """
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(id=ticket_id).first()

        if not ticket:
            return None, "Ticket not found."

        if ticket.status == "resolved":
            return None, "This ticket is already resolved."

        # Determine points
        cat_info = get_category_config(ticket.category_id) or {}

        # If points_override is provided, use it (for both variable and fixed categories)
        if points_override is not None:
            # For variable categories, validate range if bounds are set
            if cat_info.get("variable_points", False):
                min_pts = int(cat_info.get("min_points", 0))
                max_pts = int(cat_info.get("max_points", 0))
                if points_override < min_pts:
                    return None, f"Point value must be at least {min_pts}."
                if max_pts and points_override > max_pts:
                    return None, f"Point value must be at most {max_pts}."
            point_penalty = points_override
        else:
            # No override provided
            if cat_info.get("variable_points", False):
                # Variable categories require an explicit value
                return (
                    None,
                    "This category requires an explicit point value.",
                )
            # Use default for fixed categories
            point_penalty = cat_info.get("points", 0)

        resolver = get_user_for_ticket(discord_id=discord_id, user=user)

        # Update ticket
        ticket.status = "resolved"
        ticket.resolved_at = timezone.now()
        ticket.resolved_by = resolver
        ticket.resolution_notes = resolution_notes
        ticket.points_charged = point_penalty

        # If not already assigned, mark as assigned to resolver
        if not ticket.assigned_to and resolver:
            ticket.assigned_to = resolver

        # Schedule thread archiving if Discord thread exists
        if ticket.discord_thread_id:
            from datetime import timedelta

            ticket.thread_archive_scheduled_at = timezone.now() + timedelta(seconds=60)

        ticket.save()

        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            action="resolved",
            actor=resolver,
            details={
                "resolved_by": actor_username,
                "discord_username": discord_username,
                "authentik_username": resolver.username if resolver else None,
                "notes": resolution_notes,
                "point_penalty": point_penalty,
            },
        )

        return ticket, None


async def aresolve_ticket_atomic(
    ticket_id: int,
    actor_username: str,
    resolution_notes: str = "",
    points_override: int | None = None,
    discord_id: int | None = None,
    discord_username: str | None = None,
    user: User | None = None,
) -> tuple[Ticket | None, str | None]:
    """Async wrapper for resolve_ticket_atomic."""
    return await sync_to_async(resolve_ticket_atomic)(
        ticket_id=ticket_id,
        actor_username=actor_username,
        resolution_notes=resolution_notes,
        points_override=points_override,
        discord_id=discord_id,
        discord_username=discord_username,
        user=user,
    )


def unclaim_ticket_atomic(
    ticket_id: int,
    actor_username: str,
    user: User | None = None,
) -> tuple[Ticket | None, str | None]:
    """
    Unclaim a ticket atomically.

    Args:
        ticket_id: ID of ticket to unclaim
        actor_username: Username for history (e.g., "discord:user" or "web:user")
        user: User performing the unclaim (optional, for history)

    Returns:
        Tuple of (ticket, error_message). If error, ticket is None.
    """
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(id=ticket_id).first()

        if not ticket:
            return None, "Ticket not found."

        if ticket.status != "claimed":
            return None, f"Cannot unclaim ticket with status: {ticket.status}."

        # Reset ticket to open
        ticket.status = "open"
        ticket.assigned_to = None
        ticket.assigned_at = None
        ticket.save()

        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            action="unclaimed",
            actor=user,
            details={"unclaimed_by": actor_username},
        )

        return ticket, None


async def aunclaim_ticket_atomic(
    ticket_id: int,
    actor_username: str,
    user: User | None = None,
) -> tuple[Ticket | None, str | None]:
    """Async wrapper for unclaim_ticket_atomic."""
    return await sync_to_async(unclaim_ticket_atomic)(
        ticket_id=ticket_id,
        actor_username=actor_username,
        user=user,
    )


def reassign_ticket_atomic(
    ticket_id: int,
    actor_username: str,
    discord_id: int | None = None,
    discord_username: str | None = None,
    user: User | None = None,
) -> tuple[Ticket | None, str | None]:
    """
    Reassign a claimed ticket to another support member atomically.

    Args:
        ticket_id: ID of ticket to reassign
        actor_username: Username for history (e.g., "discord:user" or "web:user")
        discord_id: Discord user ID of new assignee (optional, used to look up User)
        discord_username: Discord username of new assignee (optional, for history only)
        user: Django User object of new assignee (preferred)

    Returns:
        Tuple of (ticket, error_message). If error, ticket is None.
    """
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(id=ticket_id).first()

        if not ticket:
            return None, "Ticket not found."

        if ticket.status != "claimed":
            return None, f"Can only reassign claimed tickets. This ticket is {ticket.status}."

        previous_assignee = ticket.assigned_to.username if ticket.assigned_to else None

        new_assignee = get_user_for_ticket(discord_id=discord_id, user=user)

        if not new_assignee:
            return None, "Could not find a valid user for the new assignee."

        # Update ticket assignment
        ticket.assigned_to = new_assignee
        ticket.assigned_at = timezone.now()
        ticket.save()

        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            action="reassigned",
            actor=new_assignee,
            details={
                "reassigned_by": actor_username,
                "previous_assignee": previous_assignee,
                "new_assignee": new_assignee.username,
            },
        )

        return ticket, None


async def areassign_ticket_atomic(
    ticket_id: int,
    actor_username: str,
    discord_id: int | None = None,
    discord_username: str | None = None,
    user: User | None = None,
) -> tuple[Ticket | None, str | None]:
    """Async wrapper for reassign_ticket_atomic."""
    return await sync_to_async(reassign_ticket_atomic)(
        ticket_id=ticket_id,
        actor_username=actor_username,
        discord_id=discord_id,
        discord_username=discord_username,
        user=user,
    )
