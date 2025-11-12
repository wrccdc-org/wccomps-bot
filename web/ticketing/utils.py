"""Ticketing utilities for atomic ticket creation and lifecycle management."""

from typing import Optional, Tuple, cast
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from asgiref.sync import sync_to_async

from core.tickets_config import TICKET_CATEGORIES
from team.models import Team
from ticketing.models import Ticket, TicketHistory


def create_ticket_atomic(
    team: Team,
    category: str,
    title: str,
    description: str = "",
    hostname: str = "",
    ip_address: Optional[str] = None,
    service_name: str = "",
    actor_username: str = "system",
) -> Ticket:
    """
    Create a ticket with atomic ticket number generation.

    Uses transaction with select_for_update() to prevent race conditions.

    Args:
        team: Team to create ticket for
        category: Ticket category (must be in TICKET_CATEGORIES)
        title: Ticket title
        description: Ticket description
        hostname: Hostname (optional)
        ip_address: IP address (optional)
        service_name: Service name (optional)
        actor_username: Username of person creating ticket (for history)

    Returns:
        Created Ticket instance
    """
    cat_info = TICKET_CATEGORIES[category]

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
            points_charged=cat_info.get("points", 0),
        )

        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            action="created",
            actor_username=actor_username,
            details=f"Ticket created via {actor_username}",
        )

    return ticket


async def acreate_ticket_atomic(
    team: Team,
    category: str,
    title: str,
    description: str = "",
    hostname: str = "",
    ip_address: Optional[str] = None,
    service_name: str = "",
    actor_username: str = "discord",
) -> Ticket:
    """
    Async version of create_ticket_atomic for Discord bot usage.

    Wraps the sync version to ensure proper transaction handling.

    Args:
        team: Team to create ticket for
        category: Ticket category (must be in TICKET_CATEGORIES)
        title: Ticket title
        description: Ticket description
        hostname: Hostname (optional)
        ip_address: IP address (optional)
        service_name: Service name (optional)
        actor_username: Username of person creating ticket (for history)

    Returns:
        Created Ticket instance
    """

    @sync_to_async
    def create_sync() -> Ticket:
        return create_ticket_atomic(
            team=team,
            category=category,
            title=title,
            description=description,
            hostname=hostname,
            ip_address=ip_address,
            service_name=service_name,
            actor_username=actor_username,
        )

    return await create_sync()


def claim_ticket_atomic(
    ticket_id: int,
    actor_username: str,
    discord_id: Optional[int] = None,
    discord_username: Optional[str] = None,
    authentik_username: Optional[str] = None,
    authentik_user_id: Optional[str] = None,
) -> Tuple[Optional[Ticket], Optional[str]]:
    """
    Claim a ticket atomically with race condition protection.

    Args:
        ticket_id: ID of ticket to claim
        actor_username: Username for history (e.g., "discord:user" or "web:user")
        discord_id: Discord user ID (optional)
        discord_username: Discord username (optional)
        authentik_username: Authentik username (optional)
        authentik_user_id: Authentik user ID (optional)

    Returns:
        Tuple of (ticket, error_message). If error, ticket is None.
    """
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(id=ticket_id).first()

        if not ticket:
            return None, "Ticket not found."

        if ticket.status != "open":
            return None, f"This ticket is already {ticket.status}."

        # Update ticket
        ticket.status = "claimed"
        ticket.assigned_to_discord_id = discord_id
        ticket.assigned_to_discord_username = discord_username or ""
        ticket.assigned_to_authentik_username = authentik_username or ""
        ticket.assigned_to_authentik_user_id = authentik_user_id or ""
        ticket.assigned_at = timezone.now()
        ticket.save()

        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            action="claimed",
            actor_username=actor_username,
            details={
                "claimed_by": actor_username,
                "discord_username": discord_username,
                "authentik_username": authentik_username,
            },
        )

        return ticket, None


async def aclaim_ticket_atomic(
    ticket_id: int,
    actor_username: str,
    discord_id: Optional[int] = None,
    discord_username: Optional[str] = None,
    authentik_username: Optional[str] = None,
    authentik_user_id: Optional[str] = None,
) -> Tuple[Optional[Ticket], Optional[str]]:
    """
    Async version of claim_ticket_atomic.

    Args:
        ticket_id: ID of ticket to claim
        actor_username: Username for history (e.g., "discord:user" or "web:user")
        discord_id: Discord user ID (optional)
        discord_username: Discord username (optional)
        authentik_username: Authentik username (optional)
        authentik_user_id: Authentik user ID (optional)

    Returns:
        Tuple of (ticket, error_message). If error, ticket is None.
    """

    @sync_to_async
    def claim_atomic() -> Tuple[Optional[Ticket], Optional[str]]:
        return claim_ticket_atomic(
            ticket_id=ticket_id,
            actor_username=actor_username,
            discord_id=discord_id,
            discord_username=discord_username,
            authentik_username=authentik_username,
            authentik_user_id=authentik_user_id,
        )

    return await claim_atomic()


def resolve_ticket_atomic(
    ticket_id: int,
    actor_username: str,
    resolution_notes: str = "",
    points_override: Optional[int] = None,
    discord_id: Optional[int] = None,
    discord_username: Optional[str] = None,
    authentik_username: Optional[str] = None,
    authentik_user_id: Optional[str] = None,
) -> Tuple[Optional[Ticket], Optional[str]]:
    """
    Resolve a ticket atomically.

    Args:
        ticket_id: ID of ticket to resolve
        actor_username: Username for history (e.g., "discord:user" or "web:user")
        resolution_notes: Notes describing resolution
        points_override: Override points for variable-point categories
        discord_id: Discord user ID (optional)
        discord_username: Discord username (optional)
        authentik_username: Authentik username (optional)
        authentik_user_id: Authentik user ID (optional)

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
        cat_info = TICKET_CATEGORIES.get(ticket.category, {})

        # If points_override is provided, use it (for both variable and fixed categories)
        if points_override is not None:
            # For variable categories, validate range
            if cat_info.get("variable_points", False):
                min_pts = cast(int, cat_info.get("min_points", 0))
                max_pts = cast(int, cat_info.get("max_points", 0))
                if points_override < min_pts or points_override > max_pts:
                    return None, f"Point value must be between {min_pts} and {max_pts}."
            point_penalty = points_override
        else:
            # No override provided
            if cat_info.get("variable_points", False):
                # Variable categories require an explicit value
                min_pts = cast(int, cat_info.get("min_points", 0))
                max_pts = cast(int, cat_info.get("max_points", 0))
                return (
                    None,
                    f"This category requires a point value between {min_pts} and {max_pts}.",
                )
            # Use default for fixed categories
            point_penalty = cast(int, cat_info.get("points", 0))

        # Update ticket
        ticket.status = "resolved"
        ticket.resolved_at = timezone.now()
        ticket.resolved_by_discord_id = discord_id
        ticket.resolved_by_discord_username = discord_username or ""
        ticket.resolved_by_authentik_username = authentik_username or ""
        ticket.resolved_by_authentik_user_id = authentik_user_id or ""
        ticket.resolution_notes = resolution_notes
        ticket.points_charged = point_penalty

        # If not already assigned, mark as assigned to resolver
        if not ticket.assigned_to_discord_id and discord_id:
            ticket.assigned_to_discord_id = discord_id
            ticket.assigned_to_discord_username = discord_username or ""
        if not ticket.assigned_to_authentik_username and authentik_username:
            ticket.assigned_to_authentik_username = authentik_username
            ticket.assigned_to_authentik_user_id = authentik_user_id or ""

        # Schedule thread archiving if Discord thread exists
        if ticket.discord_thread_id:
            from datetime import timedelta

            ticket.thread_archive_scheduled_at = timezone.now() + timedelta(seconds=60)

        ticket.save()

        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            action="resolved",
            actor_username=actor_username,
            details={
                "resolved_by": actor_username,
                "discord_username": discord_username,
                "authentik_username": authentik_username,
                "notes": resolution_notes,
                "point_penalty": point_penalty,
            },
        )

        return ticket, None


async def aresolve_ticket_atomic(
    ticket_id: int,
    actor_username: str,
    resolution_notes: str = "",
    points_override: Optional[int] = None,
    discord_id: Optional[int] = None,
    discord_username: Optional[str] = None,
    authentik_username: Optional[str] = None,
    authentik_user_id: Optional[str] = None,
) -> Tuple[Optional[Ticket], Optional[str]]:
    """
    Async version of resolve_ticket_atomic.

    Args:
        ticket_id: ID of ticket to resolve
        actor_username: Username for history (e.g., "discord:user" or "web:user")
        resolution_notes: Notes describing resolution
        points_override: Override points for variable-point categories
        discord_id: Discord user ID (optional)
        discord_username: Discord username (optional)
        authentik_username: Authentik username (optional)
        authentik_user_id: Authentik user ID (optional)

    Returns:
        Tuple of (ticket, error_message). If error, ticket is None.
    """

    @sync_to_async
    def resolve_atomic() -> Tuple[Optional[Ticket], Optional[str]]:
        return resolve_ticket_atomic(
            ticket_id=ticket_id,
            actor_username=actor_username,
            resolution_notes=resolution_notes,
            points_override=points_override,
            discord_id=discord_id,
            discord_username=discord_username,
            authentik_username=authentik_username,
            authentik_user_id=authentik_user_id,
        )

    return await resolve_atomic()


def unclaim_ticket_atomic(
    ticket_id: int,
    actor_username: str,
) -> Tuple[Optional[Ticket], Optional[str]]:
    """
    Unclaim a ticket atomically.

    Args:
        ticket_id: ID of ticket to unclaim
        actor_username: Username for history (e.g., "discord:user" or "web:user")

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
        ticket.assigned_to_discord_id = None
        ticket.assigned_to_discord_username = ""
        ticket.assigned_to_authentik_username = ""
        ticket.assigned_to_authentik_user_id = ""
        ticket.assigned_at = None
        ticket.save()

        # Create history entry
        TicketHistory.objects.create(
            ticket=ticket,
            action="unclaimed",
            actor_username=actor_username,
            details={"unclaimed_by": actor_username},
        )

        return ticket, None


async def aunclaim_ticket_atomic(
    ticket_id: int,
    actor_username: str,
) -> Tuple[Optional[Ticket], Optional[str]]:
    """
    Async version of unclaim_ticket_atomic.

    Args:
        ticket_id: ID of ticket to unclaim
        actor_username: Username for history (e.g., "discord:user" or "web:user")

    Returns:
        Tuple of (ticket, error_message). If error, ticket is None.
    """

    @sync_to_async
    def unclaim_atomic() -> Tuple[Optional[Ticket], Optional[str]]:
        return unclaim_ticket_atomic(
            ticket_id=ticket_id,
            actor_username=actor_username,
        )

    return await unclaim_atomic()
