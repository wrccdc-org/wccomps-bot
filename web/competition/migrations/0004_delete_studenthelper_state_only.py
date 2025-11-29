# Move StudentHelper to person app (state only - table stays)

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("competition", "0003_delete_competition_model"),
    ]

    # Use state_operations to remove model from Django state
    # without actually dropping the database table
    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(
                    name="StudentHelper",
                ),
            ],
            database_operations=[],
        ),
    ]
