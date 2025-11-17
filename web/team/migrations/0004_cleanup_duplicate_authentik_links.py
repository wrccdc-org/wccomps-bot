# Migration to deactivate duplicate authentik_user_id links before adding constraint
from typing import Any
from django.db import migrations
from django.utils import timezone


def deactivate_duplicate_authentik_links(apps: Any, schema_editor: Any) -> None:
    """
    Deactivate all but the most recent active DiscordLink for each authentik_user_id.
    This prevents the unique constraint from failing on existing data.
    """
    DiscordLink = apps.get_model("team", "DiscordLink")

    # Find all authentik_user_ids that have multiple active links
    from django.db.models import Count

    duplicates = (
        DiscordLink.objects.filter(is_active=True)
        .values("authentik_user_id")
        .annotate(count=Count("id"))
        .filter(count__gt=1)
    )

    for dup in duplicates:
        authentik_user_id = dup["authentik_user_id"]

        # Get all active links for this authentik_user_id, ordered by most recent first
        links = DiscordLink.objects.filter(
            authentik_user_id=authentik_user_id, is_active=True
        ).order_by("-linked_at")

        # Keep the most recent one, deactivate the rest
        for link in list(links[1:]):
            link.is_active = False
            link.unlinked_at = timezone.now()
            link.save()


class Migration(migrations.Migration):
    dependencies = [
        ("team", "0003_fix_sequences"),
    ]

    operations = [
        migrations.RunPython(
            deactivate_duplicate_authentik_links,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
