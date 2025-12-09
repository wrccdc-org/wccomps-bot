"""Delete the Person model - data has been migrated to DiscordLink."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("person", "0004_increase_authentik_user_id_length"),
        ("team", "0006_migrate_helper_data"),
        ("ticketing", "0005_change_fks_to_discordlink"),
    ]

    operations = [
        migrations.DeleteModel(
            name="Person",
        ),
    ]
