"""Migration to change Ticket FKs from DiscordLink to User.

This converts the FK references from DiscordLink.id to the User.id
that the DiscordLink is linked to.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def migrate_discordlink_to_user(apps, schema_editor):
    """Convert DiscordLink FKs to User FKs."""
    Ticket = apps.get_model("ticketing", "Ticket")
    TicketComment = apps.get_model("ticketing", "TicketComment")
    TicketHistory = apps.get_model("ticketing", "TicketHistory")
    DiscordLink = apps.get_model("team", "DiscordLink")

    # Build DiscordLink.id -> User.id mapping
    link_to_user = {}
    for link in DiscordLink.objects.select_related("user").all():
        if link.user_id:
            link_to_user[link.id] = link.user_id

    # Migrate Ticket.assigned_to and Ticket.resolved_by
    for ticket in Ticket.objects.all():
        changed = False
        if ticket.assigned_to_id and ticket.assigned_to_id in link_to_user:
            ticket.assigned_to_id = link_to_user[ticket.assigned_to_id]
            changed = True
        elif ticket.assigned_to_id:
            ticket.assigned_to_id = None
            changed = True

        if ticket.resolved_by_id and ticket.resolved_by_id in link_to_user:
            ticket.resolved_by_id = link_to_user[ticket.resolved_by_id]
            changed = True
        elif ticket.resolved_by_id:
            ticket.resolved_by_id = None
            changed = True

        if changed:
            ticket.save(update_fields=["assigned_to_id", "resolved_by_id"])

    # Migrate TicketComment.author
    for comment in TicketComment.objects.all():
        if comment.author_id and comment.author_id in link_to_user:
            comment.author_id = link_to_user[comment.author_id]
            comment.save(update_fields=["author_id"])
        elif comment.author_id:
            comment.author_id = None
            comment.save(update_fields=["author_id"])

    # Migrate TicketHistory.actor
    for history in TicketHistory.objects.all():
        if history.actor_id and history.actor_id in link_to_user:
            history.actor_id = link_to_user[history.actor_id]
            history.save(update_fields=["actor_id"])
        elif history.actor_id:
            history.actor_id = None
            history.save(update_fields=["actor_id"])


def reverse_migrate(apps, schema_editor):
    """Reverse migration - not fully reversible."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("ticketing", "0005_change_fks_to_discordlink"),
        ("team", "0006_migrate_helper_data"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Step 1: Migrate data from DiscordLink IDs to User IDs
        migrations.RunPython(migrate_discordlink_to_user, reverse_migrate),
        # Step 2: Update the FK references to point to User model
        migrations.AlterField(
            model_name="ticket",
            name="assigned_to",
            field=models.ForeignKey(
                blank=True,
                help_text="User assigned to this ticket",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_tickets",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="ticket",
            name="resolved_by",
            field=models.ForeignKey(
                blank=True,
                help_text="User who resolved this ticket",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="resolved_tickets",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="ticketcomment",
            name="author",
            field=models.ForeignKey(
                blank=True,
                help_text="User who authored this comment",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="ticket_comments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="tickethistory",
            name="actor",
            field=models.ForeignKey(
                blank=True,
                help_text="User who performed this action",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="ticket_history_entries",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
