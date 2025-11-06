"""Fix PostgreSQL sequences that got out of sync from data imports."""

from django.db import migrations


def fix_sequences(apps, schema_editor):
    """Reset all sequences to match their table's max ID."""
    if schema_editor.connection.vendor != "postgresql":
        return

    with schema_editor.connection.cursor() as cursor:
        # Fix all team app sequences
        sequences = [
            ("team_linkratelimit_id_seq", "team_linkratelimit"),
            ("team_linkattempt_id_seq", "team_linkattempt"),
            ("team_linktoken_id_seq", "team_linktoken"),
            ("team_discordlink_id_seq", "team_discordlink"),
            ("team_team_id_seq", "team_team"),
        ]

        for seq_name, table_name in sequences:
            cursor.execute(
                f"SELECT setval('{seq_name}', (SELECT COALESCE(MAX(id), 0) FROM {table_name}));"
            )


class Migration(migrations.Migration):
    dependencies = [
        ("team", "0002_copy_data_from_core"),
    ]

    operations = [
        migrations.RunPython(fix_sequences, reverse_code=migrations.RunPython.noop),
    ]
