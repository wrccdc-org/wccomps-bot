# Generated manually to make team_id nullable for non-team accounts

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_schoolinfo_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="discordlink",
            name="team",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="members",
                to="core.team",
            ),
        ),
    ]
