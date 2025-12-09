"""Convert screenshot models from ImageField to BinaryField storage.

This migration:
1. Renames 'image' column to 'filename' (preserves original file path as record)
2. Adds new columns: file_data (nullable for existing records), mime_type

Existing records are preserved but will have empty file_data (files were lost).
New uploads will store binary data directly in the database.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scoring", "0008_make_max_points_nullable"),
    ]

    operations = [
        # IncidentScreenshot changes
        migrations.RenameField(
            model_name="incidentscreenshot",
            old_name="image",
            new_name="filename",
        ),
        migrations.AlterField(
            model_name="incidentscreenshot",
            name="filename",
            field=models.CharField(max_length=255),
        ),
        migrations.AddField(
            model_name="incidentscreenshot",
            name="file_data",
            field=models.BinaryField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="incidentscreenshot",
            name="mime_type",
            field=models.CharField(default="image/png", max_length=100),
        ),

        # RedTeamScreenshot changes
        migrations.RenameField(
            model_name="redteamscreenshot",
            old_name="image",
            new_name="filename",
        ),
        migrations.AlterField(
            model_name="redteamscreenshot",
            name="filename",
            field=models.CharField(max_length=255),
        ),
        migrations.AddField(
            model_name="redteamscreenshot",
            name="file_data",
            field=models.BinaryField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name="redteamscreenshot",
            name="mime_type",
            field=models.CharField(default="image/png", max_length=100),
        ),
    ]
