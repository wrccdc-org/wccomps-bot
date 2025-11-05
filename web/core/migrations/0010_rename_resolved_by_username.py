# Generated manually
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_consolidate_claimed_in_progress"),
    ]

    operations = [
        migrations.RenameField(
            model_name="ticket",
            old_name="resolved_by_username",
            new_name="resolved_by_discord_username",
        ),
    ]
