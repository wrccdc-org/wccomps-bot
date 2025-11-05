# Convert all in_progress tickets to claimed

from django.db import migrations
from django.apps.registry import Apps
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def convert_in_progress_to_claimed(
    apps: Apps, schema_editor: BaseDatabaseSchemaEditor
) -> None:
    """Convert all in_progress tickets to claimed."""
    Ticket = apps.get_model("core", "Ticket")
    Ticket.objects.filter(status="in_progress").update(status="claimed")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_remove_priority"),
    ]

    operations = [
        migrations.RunPython(
            convert_in_progress_to_claimed,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
