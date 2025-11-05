# Remove author_type field from TicketComment

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0006_remove_pointadjustment"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="ticketcomment",
            name="author_type",
        ),
    ]
