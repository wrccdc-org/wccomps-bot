"""Update related_names after RedTeamFinding -> RedTeamScore rename."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("scoring", "0025_rename_redteamfinding_to_redteamscore"),
        ("registration", "0001_initial"),
        ("team", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="redteamscore",
            name="event",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="red_team_scores",
                to="registration.event",
            ),
        ),
        migrations.AlterField(
            model_name="redteamscore",
            name="submitted_by",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="red_scores_submitted",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="redteamscore",
            name="approved_by",
            field=models.ForeignKey(
                blank=True,
                help_text="Gold Team member who approved this finding",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="red_scores_approved",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="redteamscore",
            name="affected_teams",
            field=models.ManyToManyField(
                help_text="Teams affected by this finding",
                related_name="red_team_scores",
                to="team.team",
            ),
        ),
    ]
