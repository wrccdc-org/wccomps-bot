"""Rename RedTeamFinding to RedTeamScore and matched_to_red_finding to matched_to_red_score."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("scoring", "0024_alter_injectscore_options_and_more"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="RedTeamFinding",
            new_name="RedTeamScore",
        ),
        migrations.RenameField(
            model_name="incidentreport",
            old_name="matched_to_red_finding",
            new_name="matched_to_red_score",
        ),
    ]
