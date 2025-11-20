"""Fix PostgreSQL sequences that got out of sync from data imports."""

from typing import Any

from django.db import migrations
from psycopg2 import sql


def fix_sequences(apps: Any, schema_editor: Any) -> None:
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
            # Get max ID, default to 1 if table is empty (setval doesn't accept 0)
            query = sql.SQL("SELECT setval({seq}, (SELECT COALESCE(MAX(id), 1) FROM {table}), false);").format(
                seq=sql.Literal(seq_name),
                table=sql.Identifier(table_name),
            )
            cursor.execute(query)


class Migration(migrations.Migration):
    dependencies = [
        ("team", "0002_copy_data_from_core"),
    ]

    operations = [
        migrations.RunPython(fix_sequences, reverse_code=migrations.RunPython.noop),
    ]
