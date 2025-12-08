"""
Data migration: SocialAccount → UserGroups, populate DiscordLink.user

This migration:
1. Copies data from allauth's SocialAccount to core.UserGroups
2. Populates team.DiscordLink.user by matching authentik_user_id to UserGroups.authentik_id

After this migration succeeds:
- The allauth tables can be dropped (via removing 'allauth' from INSTALLED_APPS)
- DiscordLink.user can be made NOT NULL
- Legacy DiscordLink fields (authentik_username, authentik_user_id) can be removed
"""

from django.db import migrations


def migrate_social_accounts_to_usergroups(apps, schema_editor):
    """Copy SocialAccount data to UserGroups."""
    # Try to get SocialAccount - it may not exist if allauth was never installed
    try:
        SocialAccount = apps.get_model("socialaccount", "SocialAccount")
    except LookupError:
        # allauth tables don't exist, nothing to migrate
        return

    UserGroups = apps.get_model("core", "UserGroups")

    for social_account in SocialAccount.objects.filter(provider="authentik"):
        # Skip if UserGroups already exists for this user
        if UserGroups.objects.filter(user_id=social_account.user_id).exists():
            continue

        # Get groups from extra_data
        # Production data stores groups in extra_data['id_token']['groups']
        extra_data = social_account.extra_data or {}
        id_token = extra_data.get("id_token", {})
        groups = id_token.get("groups", [])

        UserGroups.objects.create(
            user_id=social_account.user_id,
            authentik_id=social_account.uid,
            groups=groups,
        )


def populate_discord_link_users(apps, schema_editor):
    """Populate DiscordLink.user by matching authentik_user_id to UserGroups.authentik_id."""
    DiscordLink = apps.get_model("team", "DiscordLink")
    UserGroups = apps.get_model("core", "UserGroups")

    # Build lookup: authentik_id → user_id
    authentik_to_user = {
        ug.authentik_id: ug.user_id for ug in UserGroups.objects.all()
    }

    # Update DiscordLinks that don't have a user set
    for link in DiscordLink.objects.filter(user__isnull=True):
        user_id = authentik_to_user.get(link.authentik_user_id)
        if user_id:
            link.user_id = user_id
            link.save(update_fields=["user"])


def migrate_forward(apps, schema_editor):
    """Run both migrations in order."""
    migrate_social_accounts_to_usergroups(apps, schema_editor)
    populate_discord_link_users(apps, schema_editor)


def migrate_backward(apps, schema_editor):
    """Reverse migration - clear DiscordLink.user and delete UserGroups.

    Note: This does NOT restore SocialAccount data since we don't have enough
    info to recreate extra_data. Use database backup if full rollback needed.
    """
    DiscordLink = apps.get_model("team", "DiscordLink")
    UserGroups = apps.get_model("core", "UserGroups")

    # Clear DiscordLink.user
    DiscordLink.objects.update(user=None)

    # Delete all UserGroups (they were created by this migration)
    UserGroups.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_identity_architecture"),
        ("team", "0002_identity_architecture"),
        # Only depend on socialaccount if it exists
        # Comment this out if socialaccount tables were already dropped
        # ("socialaccount", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(migrate_forward, migrate_backward),
    ]
