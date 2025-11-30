from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("scoring", "0006_injectgrade_approved_at_injectgrade_approved_by_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="orangechecktype",
            name="default_points",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="Default point value when this check type is selected",
                max_digits=10,
            ),
        ),
    ]
