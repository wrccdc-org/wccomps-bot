# Coalesced migration combining 0003-0006

from typing import Any
from django.db import migrations, models, connection
import django.db.models.deletion


def create_sequence_if_postgres(apps: Any, schema_editor: Any) -> None:
    """Create PostgreSQL sequence only if using PostgreSQL."""
    if connection.vendor == "postgresql":
        schema_editor.execute(
            "CREATE SEQUENCE IF NOT EXISTS ticket_number_seq START 1;"
        )


def drop_sequence_if_postgres(apps: Any, schema_editor: Any) -> None:
    """Drop PostgreSQL sequence only if using PostgreSQL."""
    if connection.vendor == "postgresql":
        schema_editor.execute("DROP SEQUENCE IF EXISTS ticket_number_seq;")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_add_competition_config"),
    ]

    operations = [
        # Add max_team_members to CompetitionConfig
        migrations.AddField(
            model_name="competitionconfig",
            name="max_team_members",
            field=models.IntegerField(default=10, help_text="Maximum members per team"),
        ),
        # Create PostgreSQL sequence for ticket numbering (PostgreSQL only)
        migrations.RunPython(
            create_sequence_if_postgres,
            reverse_code=drop_sequence_if_postgres,
        ),
        # Remove deduplication fields from Ticket model
        migrations.RemoveField(
            model_name="ticket",
            name="related_ticket",
        ),
        migrations.RemoveField(
            model_name="ticket",
            name="dedup_group",
        ),
        migrations.RemoveField(
            model_name="ticket",
            name="points_waived",
        ),
        # Add tags field to Ticket model
        migrations.AddField(
            model_name="ticket",
            name="tags",
            field=models.JSONField(blank=True, default=list),
        ),
        # Create LinkRateLimit model
        migrations.CreateModel(
            name="LinkRateLimit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("discord_id", models.BigIntegerField()),
                ("attempted_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["discord_id", "-attempted_at"],
                        name="core_linkra_discord_5a8b9c_idx",
                    ),
                ],
            },
        ),
        # Create CommentRateLimit model
        migrations.CreateModel(
            name="CommentRateLimit",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("discord_id", models.BigIntegerField()),
                ("posted_at", models.DateTimeField(auto_now_add=True)),
                (
                    "ticket",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="core.ticket",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["ticket", "-posted_at"], name="core_commen_ticket__idx"
                    ),
                    models.Index(
                        fields=["discord_id", "-posted_at"],
                        name="core_commen_discord_idx",
                    ),
                ],
            },
        ),
    ]
