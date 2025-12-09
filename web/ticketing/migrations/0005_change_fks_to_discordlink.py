"""Migration to add DiscordLink FKs to ticketing models.

NOTE: This migration was originally a data migration from Person to DiscordLink.
The person app has been deleted. This migration now directly adds the DiscordLink FKs.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("team", "0006_migrate_helper_data"),
        ("ticketing", "0004_remove_denormalized_fields"),
    ]

    operations = [
        migrations.AddField(
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
        migrations.AddField(
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
        migrations.AddField(
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
        migrations.AddField(
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
        migrations.AddIndex(
            model_name="ticket",
            index=models.Index(fields=["assigned_to"], name="ticketing_t_assigne_bc985f_idx"),
        ),
    ]
