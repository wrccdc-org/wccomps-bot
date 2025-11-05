# Generated manually
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0010_rename_resolved_by_username"),
    ]

    operations = [
        migrations.AddField(
            model_name="ticket",
            name="assigned_to_authentik_username",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="ticket",
            name="assigned_to_authentik_user_id",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="ticket",
            name="resolved_by_authentik_username",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="ticket",
            name="resolved_by_authentik_user_id",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
