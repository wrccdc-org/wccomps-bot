"""Quotient API integration for scoring system."""

from decimal import Decimal
from typing import Any

from django.contrib.auth.models import User
from quotient.client import QuotientClient

from team.models import Team

from .models import QuotientMetadataCache, ServiceScore


def sync_quotient_metadata(user: User | None = None) -> QuotientMetadataCache:
    """
    Sync infrastructure metadata from Quotient.

    This populates dropdowns for boxes, services, and IP addresses.

    Args:
        user: User performing the sync (optional)

    Returns:
        QuotientMetadataCache instance
    """
    client = QuotientClient()
    infrastructure = client.get_infrastructure()

    if not infrastructure:
        raise ValueError("Failed to retrieve infrastructure from Quotient")

    # Convert infrastructure to JSON-serializable format
    boxes_data: list[dict[str, Any]] = []
    services_data: list[dict[str, Any]] = []

    for box in infrastructure.boxes:
        box_dict: dict[str, Any] = {
            "name": box.name,
            "ip": box.ip,
            "services": [],
        }

        for service in box.services:
            service_dict = {
                "name": service.name,
                "display_name": service.display_name,
                "type": service.type,
            }
            box_dict["services"].append(service_dict)

            # Add to global services list if not already there
            if service_dict not in services_data:
                services_data.append(service_dict)

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
        service_score, created = ServiceScore.objects.update_or_create(
            team=team,
            defaults={
                "service_points": Decimal(str(team_score.service_score)),
                # SLA violations might need to be calculated separately
                # For now, we'll leave it at 0 and calculate from service checks if needed
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
        List of (value, label) tuples for box dropdown
    """
    metadata = QuotientMetadataCache.objects.first()
    if metadata:
        return [(box["name"], box["name"]) for box in metadata.boxes]
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


def get_ip_template_for_box(box_name: str) -> str:
    """
    Get IP template for a box (e.g., 10.100.1X.22).

    Args:
        box_name: Box name

    Returns:
        IP template string
    """
    metadata = QuotientMetadataCache.objects.first()
    if not metadata:
        return ""

    for box in metadata.boxes:
        if box["name"] == box_name:
            # Replace team-specific part with X placeholder
            # Quotient uses underscore in templates (e.g., 10.100.1_.2)
            ip = str(box["ip"])
            if "_" in ip:
                return ip.replace("_", "X")
            return ip
    return ""
