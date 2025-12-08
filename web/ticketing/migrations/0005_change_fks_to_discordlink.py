"""Migration to change Ticket FKs from Person to DiscordLink.

This is a multi-step migration:
1. Add new nullable DiscordLink FK columns
2. Migrate data: Person.discord_id -> DiscordLink lookup
3. Drop old Person FK columns
"""

import django.db.models.deletion
from django.db import migrations, models


def migrate_person_to_discordlink(apps, schema_editor):
    """Convert Person FKs to DiscordLink FKs."""
    Ticket = apps.get_model("ticketing", "Ticket")
    TicketComment = apps.get_model("ticketing", "TicketComment")
    TicketHistory = apps.get_model("ticketing", "TicketHistory")
    DiscordLink = apps.get_model("team", "DiscordLink")
    Person = apps.get_model("person", "Person")

    # Build discord_id -> DiscordLink mapping (active links only)
    discord_to_link = {}
    for link in DiscordLink.objects.filter(is_active=True):
        discord_to_link[link.discord_id] = link

    # Migrate Ticket.assigned_to and Ticket.resolved_by
    tickets_updated = 0
    for ticket in Ticket.objects.exclude(assigned_to__isnull=True) | Ticket.objects.exclude(resolved_by__isnull=True):
        changed = False

        if ticket.assigned_to_id:
            try:
                person = Person.objects.get(pk=ticket.assigned_to_id)
                if person.discord_id and person.discord_id in discord_to_link:
                    ticket.assigned_to_new = discord_to_link[person.discord_id]
                    changed = True
            except Person.DoesNotExist:
                pass

        if ticket.resolved_by_id:
            try:
                person = Person.objects.get(pk=ticket.resolved_by_id)
                if person.discord_id and person.discord_id in discord_to_link:
                    ticket.resolved_by_new = discord_to_link[person.discord_id]
                    changed = True
            except Person.DoesNotExist:
                pass

        if changed:
            ticket.save()
            tickets_updated += 1

    # Migrate TicketComment.author
    comments_updated = 0
    for comment in TicketComment.objects.exclude(author__isnull=True):
        try:
            person = Person.objects.get(pk=comment.author_id)
            if person.discord_id and person.discord_id in discord_to_link:
                comment.author_new = discord_to_link[person.discord_id]
                comment.save()
                comments_updated += 1
        except Person.DoesNotExist:
            pass

    # Migrate TicketHistory.actor
    history_updated = 0
    for history in TicketHistory.objects.exclude(actor__isnull=True):
        try:
            person = Person.objects.get(pk=history.actor_id)
            if person.discord_id and person.discord_id in discord_to_link:
                history.actor_new = discord_to_link[person.discord_id]
                history.save()
                history_updated += 1
        except Person.DoesNotExist:
            pass

    print(f"Migrated {tickets_updated} tickets, {comments_updated} comments, {history_updated} history entries")


def reverse_migrate(apps, schema_editor):
    """Reverse migration - not fully reversible but clears new columns."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("team", "0006_migrate_helper_data"),
        ("ticketing", "0004_remove_denormalized_fields"),
        ("person", "0001_initial"),
    ]

    operations = [
        # Step 1: Add new DiscordLink FK columns (named with _new suffix)
        migrations.AddField(
            model_name="ticket",
            name="assigned_to_new",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_tickets_new",
                to="team.discordlink",
            ),
        ),
        migrations.AddField(
            model_name="ticket",
            name="resolved_by_new",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="resolved_tickets_new",
                to="team.discordlink",
            ),
        ),
        migrations.AddField(
            model_name="ticketcomment",
            name="author_new",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="comments_new",
                to="team.discordlink",
            ),
        ),
        migrations.AddField(
            model_name="tickethistory",
            name="actor_new",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="history_entries_new",
                to="team.discordlink",
            ),
        ),
        # Step 2: Migrate data
        migrations.RunPython(migrate_person_to_discordlink, reverse_migrate),
        # Step 3: Remove index on assigned_to before removing the field (SQLite needs this)
        migrations.RemoveIndex(
            model_name="ticket",
            name="ticketing_t_assigne_bc985f_idx",
        ),
        # Step 4: Remove old Person FK columns
        migrations.RemoveField(
            model_name="ticket",
            name="assigned_to",
        ),
        migrations.RemoveField(
            model_name="ticket",
            name="resolved_by",
        ),
        migrations.RemoveField(
            model_name="ticketcomment",
            name="author",
        ),
        migrations.RemoveField(
            model_name="tickethistory",
            name="actor",
        ),
        # Step 5: Rename new columns to final names
        migrations.RenameField(
            model_name="ticket",
            old_name="assigned_to_new",
            new_name="assigned_to",
        ),
        migrations.RenameField(
            model_name="ticket",
            old_name="resolved_by_new",
            new_name="resolved_by",
        ),
        migrations.RenameField(
            model_name="ticketcomment",
            old_name="author_new",
            new_name="author",
        ),
        migrations.RenameField(
            model_name="tickethistory",
            old_name="actor_new",
            new_name="actor",
        ),
        # Step 6: Update help text and related_name
        migrations.AlterField(
            model_name="ticket",
            name="assigned_to",
            field=models.ForeignKey(
                blank=True,
                help_text="DiscordLink of person assigned to this ticket",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="assigned_tickets",
                to="team.discordlink",
            ),
        ),
        migrations.AlterField(
            model_name="ticket",
            name="resolved_by",
            field=models.ForeignKey(
                blank=True,
                help_text="DiscordLink of person who resolved this ticket",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="resolved_tickets",
                to="team.discordlink",
            ),
        ),
        migrations.AlterField(
            model_name="ticketcomment",
            name="author",
            field=models.ForeignKey(
                blank=True,
                help_text="DiscordLink of person who authored this comment",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="comments",
                to="team.discordlink",
            ),
        ),
        migrations.AlterField(
            model_name="tickethistory",
            name="actor",
            field=models.ForeignKey(
                blank=True,
                help_text="DiscordLink of person who performed this action",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="history_entries",
                to="team.discordlink",
            ),
        ),
        # Step 7: Re-add index on assigned_to
        migrations.AddIndex(
            model_name="ticket",
            index=models.Index(fields=["assigned_to"], name="ticketing_t_assigne_bc985f_idx"),
        ),
    ]
