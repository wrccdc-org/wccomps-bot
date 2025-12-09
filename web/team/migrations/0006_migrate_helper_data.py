"""Data migration to copy helper fields from Person to DiscordLink.

NOTE: This migration has been applied. The person app has been deleted.
The RunPython is now a no-op since the migration is already in django_migrations.
"""

from django.db import migrations


def migrate_helper_data(apps, schema_editor):
    """Copy helper fields from Person to DiscordLink. Already applied - no-op."""


def reverse_migrate(apps, schema_editor):
    """Reverse migration - not reversible after person app deletion."""


class Migration(migrations.Migration):
    dependencies = [
        ("team", "0005_add_helper_fields_to_discordlink"),
    ]

    operations = [
        migrations.RunPython(migrate_helper_data, reverse_migrate),
    ]
