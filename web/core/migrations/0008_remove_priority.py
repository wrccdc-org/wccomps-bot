# Remove priority field from Ticket

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0007_remove_author_type"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="ticket",
            name="priority",
        ),
    ]
