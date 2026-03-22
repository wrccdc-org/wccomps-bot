"""Rename app label from 'challenges' to 'orange_team' in Django metadata tables."""

from django.db import migrations


def rename_app_forward(apps, schema_editor):
    schema_editor.execute(
        "UPDATE django_content_type SET app_label = 'orange_team' WHERE app_label = 'challenges'"
    )
    schema_editor.execute(
        "UPDATE django_migrations SET app = 'orange_team' WHERE app = 'challenges'"
    )


def rename_app_reverse(apps, schema_editor):
    schema_editor.execute(
        "UPDATE django_content_type SET app_label = 'challenges' WHERE app_label = 'orange_team'"
    )
    schema_editor.execute(
        "UPDATE django_migrations SET app = 'challenges' WHERE app = 'orange_team'"
    )


class Migration(migrations.Migration):

    dependencies = [
        ('orange_team', '0004_orangefollowup'),
    ]

    operations = [
        migrations.RunPython(rename_app_forward, rename_app_reverse),
    ]
