# Data migration to update attack types to simpler list

from django.db import migrations


NEW_ATTACK_TYPES = [
    ("Default Credentials", "Login using default/unchanged passwords"),
    ("Credential Reuse", "Using credentials found elsewhere or password reuse"),
    ("Remotely Exploitable Service", "Exploiting vulnerabilities in network services"),
    ("Web Based Application", "Exploiting web application vulnerabilities"),
    ("Anonymous Access", "Accessing resources without authentication"),
    ("Data Leakage", "Sensitive data exposed or extracted"),
    ("Other", "Attack type not listed above"),
]


def update_attack_types(apps, schema_editor):
    """Update attack types to simpler list."""
    AttackType = apps.get_model('scoring', 'AttackType')

    # Deactivate all existing types except "Other"
    AttackType.objects.exclude(name="Other").update(is_active=False)

    # Create or activate the new types
    for name, description in NEW_ATTACK_TYPES:
        obj, created = AttackType.objects.get_or_create(
            name=name,
            defaults={'description': description, 'is_active': True}
        )
        if not created:
            obj.description = description
            obj.is_active = True
            obj.save()


def reverse_update(apps, schema_editor):
    """Reverse: reactivate old types, deactivate new ones."""
    AttackType = apps.get_model('scoring', 'AttackType')
    # Reactivate all types
    AttackType.objects.all().update(is_active=True)


class Migration(migrations.Migration):

    dependencies = [
        ('scoring', '0014_redteamfinding_credentials_recovered_and_more'),
    ]

    operations = [
        migrations.RunPython(update_attack_types, reverse_update),
    ]
