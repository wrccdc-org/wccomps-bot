"""Make DiscordLink.user NOT NULL now that all records have it populated."""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("team", "0002_identity_architecture"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="discordlink",
            name="user",
            field=models.ForeignKey(
                on_delete=models.CASCADE,
                related_name="discord_links",
                to=settings.AUTH_USER_MODEL,
                # No longer nullable
            ),
        ),
    ]
