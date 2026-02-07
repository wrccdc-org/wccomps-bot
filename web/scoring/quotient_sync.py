"""Quotient API integration for scoring system."""

from decimal import Decimal
from typing import TypedDict

from django.contrib.auth.models import User
from quotient.client import QuotientClient

from team.models import Team

from .models import QuotientMetadataCache, ScoringTemplate, ServiceScore


class ServiceData(TypedDict):
    """Service metadata from Quotient."""

    name: str
    display_name: str
    type: str


class BoxData(TypedDict):
    """Box metadata from Quotient."""

    name: str
    ip: str
    services: list[ServiceData]


def clear_quotient_metadata() -> None:
    """Clear cached Quotient metadata from database."""
    QuotientMetadataCache.objects.all().delete()


def sync_quotient_metadata(user: User | None = None) -> QuotientMetadataCache:
    """
    Sync infrastructure metadata from Quotient.

    This populates dropdowns for boxes, services, and IP addresses.
    If sync fails, clears cached metadata to prevent stale data.

    Args:
        user: User performing the sync (optional)

    Returns:
        QuotientMetadataCache instance

    Raises:
        ValueError: If Quotient is unreachable (also clears cached metadata)
    """
    client = QuotientClient()
    infrastructure = client.get_infrastructure()

    if not infrastructure:
        clear_quotient_metadata()
        raise ValueError("Failed to retrieve infrastructure from Quotient")

    # Convert infrastructure to JSON-serializable format
    boxes_data: list[BoxData] = []
    services_data: list[ServiceData] = []

    for box in infrastructure.boxes:
        box_services: list[ServiceData] = []

        for service in box.services:
            service_dict: ServiceData = {
                "name": service.name,
                "display_name": service.display_name,
                "type": service.type,
            }
            box_services.append(service_dict)

            # Add to global services list if not already there
            if service_dict not in services_data:
                services_data.append(service_dict)

        box_dict: BoxData = {
            "name": box.name,
            "ip": box.ip,
            "services": box_services,
        }
        boxes_data.append(box_dict)

    # Update or create metadata cache (singleton)
    metadata = QuotientMetadataCache.objects.first()
    if metadata:
        metadata.boxes = boxes_data
        metadata.services = services_data
        metadata.event_name = infrastructure.event_name
        metadata.team_count = infrastructure.team_count
        metadata.synced_by = user
        metadata.save()
    else:
        metadata = QuotientMetadataCache.objects.create(
            boxes=boxes_data,
            services=services_data,
            event_name=infrastructure.event_name,
            team_count=infrastructure.team_count,
            synced_by=user,
        )

    # Update service_max in ScoringTemplate based on total possible service checks
    # Each service check is worth points; estimate based on number of services × checks × points_per_check
    total_services = len(services_data)
    # Assuming a typical competition runs for ~8 hours with checks every 5 minutes = 96 checks
    # Each successful check is typically worth 1-10 points; use estimate of 10 points per service
    estimated_service_max = Decimal(str(total_services * 96 * 10)) if total_services > 0 else Decimal("1000")

    template = ScoringTemplate.objects.first()
    if template:
        template.service_max = estimated_service_max
        template.save(update_fields=["service_max"])
    else:
        # Create template with calculated service_max
        ScoringTemplate.objects.create(service_max=estimated_service_max)

    return metadata


def sync_service_scores(user: User | None = None) -> dict[str, int]:
    """
    Sync service scores from Quotient for all teams.

    Args:
        user: User performing the sync (optional)

    Returns:
        Dict with sync statistics
    """
    client = QuotientClient()
    scores = client.get_scores()

    if not scores:
        return {"teams_created": 0, "teams_updated": 0, "total": 0}

    teams_updated = 0
    teams_created = 0

    for team_score in scores:
        try:
            team = Team.objects.get(team_number=team_score.team_number)
        except Team.DoesNotExist:
            continue

        # Update or create service score
        # Quotient's total_score includes service points
        # Note: point_adjustments not included - uses model default for creates,
        # preserves existing value for updates
        service_score, created = ServiceScore.objects.update_or_create(
            team=team,
            defaults={
                "service_points": Decimal(str(team_score.total_score)),
                "sla_violations": Decimal("0"),
                "synced_by": user,
            },
        )

        if created:
            teams_created += 1
        else:
            teams_updated += 1

    return {
        "teams_created": teams_created,
        "teams_updated": teams_updated,
        "total": teams_created + teams_updated,
    }


def get_box_choices() -> list[tuple[str, str]]:
    """
    Get box choices for dropdowns from cached metadata.

    Returns:
        List of (value, label) tuples for box dropdown (includes last IP octet)
    """
    metadata = QuotientMetadataCache.objects.first()
    if metadata:
        choices = []
        for box in metadata.boxes:
            # Include last octet of IP for easier identification
            ip = box.get("ip", "")
            last_octet = ip.split(".")[-1] if ip else ""
            label = f".{last_octet} {box['name']}" if last_octet else box["name"]
            choices.append((box["name"], label))
        return choices
    return []


def get_service_choices(box_name: str | None = None) -> list[tuple[str, str]]:
    """
    Get service choices for dropdowns from cached metadata.

    Args:
        box_name: Optional box name to filter services by

    Returns:
        List of (value, label) tuples for service dropdown
    """
    metadata = QuotientMetadataCache.objects.first()
    if not metadata:
        return []

    if box_name:
        # Filter services by box
        for box in metadata.boxes:
            if box["name"] == box_name:
                return [(s["name"], s["display_name"] or s["name"]) for s in box["services"]]
        return []
    else:
        # Return all unique services
        return [(s["name"], s["display_name"] or s["name"]) for s in metadata.services]


def get_cached_team_count() -> int:
    """
    Get the team count from cached metadata.

    Returns:
        Team count from last sync, or 50 as default if not synced
    """
    metadata = QuotientMetadataCache.objects.first()
    if metadata and metadata.team_count > 0:
        return metadata.team_count
    return 50  # Default to 50 teams if not synced
