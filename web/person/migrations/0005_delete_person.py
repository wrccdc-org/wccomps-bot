"""Delete Person model after data has been migrated to DiscordLink."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("person", "0004_increase_authentik_user_id_length"),
        # Ensure ticketing migration runs first (removes Person FKs)
        ("ticketing", "0005_change_fks_to_discordlink"),
    ]

    operations = [
        migrations.DeleteModel(
            name="Person",
        ),
    ]
