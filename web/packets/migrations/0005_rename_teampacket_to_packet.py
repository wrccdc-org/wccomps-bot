"""Rename TeamPacket to Packet."""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("packets", "0004_teampacket_team_extras"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="TeamPacket",
            new_name="Packet",
        ),
    ]
