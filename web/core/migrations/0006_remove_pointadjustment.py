# Generated manually - Remove PointAdjustment model

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0005_make_team_nullable"),
    ]

    operations = [
        migrations.DeleteModel(
            name="PointAdjustment",
        ),
    ]
