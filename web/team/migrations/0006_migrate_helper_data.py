"""Data migration to copy helper fields from Person to DiscordLink."""

from django.db import migrations


def migrate_helper_data(apps, schema_editor):
    """Copy helper fields from Person to DiscordLink."""
    Person = apps.get_model("person", "Person")
    DiscordLink = apps.get_model("team", "DiscordLink")

    # Get all Persons with helper data
    helpers = Person.objects.filter(
        is_student_helper=True
    ) | Person.objects.exclude(helper_role_name="")

    migrated = 0
    for person in helpers:
        # Find the active DiscordLink for this Person's discord_id
        discord_link = DiscordLink.objects.filter(
            discord_id=person.discord_id,
            is_active=True
        ).first()

        if discord_link:
            discord_link.is_student_helper = person.is_student_helper
            discord_link.helper_role_name = person.helper_role_name
            discord_link.helper_role_id = person.helper_role_id
            discord_link.helper_activated_at = person.helper_activated_at
            discord_link.helper_deactivated_at = person.helper_deactivated_at
            discord_link.helper_removal_reason = person.helper_removal_reason
            discord_link.save()
            migrated += 1

    print(f"Migrated helper data for {migrated} DiscordLinks")


def reverse_migrate(apps, schema_editor):
    """Reverse migration - copy helper data back to Person."""
    Person = apps.get_model("person", "Person")
    DiscordLink = apps.get_model("team", "DiscordLink")

    # Get all DiscordLinks with helper data
    helpers = DiscordLink.objects.filter(
        is_student_helper=True
    ) | DiscordLink.objects.exclude(helper_role_name="")

    for discord_link in helpers:
        try:
            person = Person.objects.get(discord_id=discord_link.discord_id)
            person.is_student_helper = discord_link.is_student_helper
            person.helper_role_name = discord_link.helper_role_name
            person.helper_role_id = discord_link.helper_role_id
            person.helper_activated_at = discord_link.helper_activated_at
            person.helper_deactivated_at = discord_link.helper_deactivated_at
            person.helper_removal_reason = discord_link.helper_removal_reason
            person.save()
        except Person.DoesNotExist:
            pass


class Migration(migrations.Migration):

    dependencies = [
        ("team", "0005_add_helper_fields_to_discordlink"),
        ("person", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(migrate_helper_data, reverse_migrate),
    ]
