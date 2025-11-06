"""Person app models - User profiles with Authentik integration."""

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


class Person(models.Model):
    """
    Extended user profile with Authentik and Discord integration.

    Caches Authentik user data to avoid repeated SocialAccount queries.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="person",
        help_text="Django user account",
    )

    # Authentik identifiers
    authentik_username = models.CharField(
        max_length=150,
        db_index=True,
        help_text="Preferred username from Authentik",
    )
    authentik_user_id = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Authentik user UUID (pk)",
    )
    authentik_email = models.EmailField(
        max_length=254,
        blank=True,
        help_text="Email from Authentik",
    )

    # Authentik groups (cached)
    authentik_groups = models.JSONField(
        default=list,
        help_text="Cached list of Authentik group names",
    )

    # Discord integration
    discord_id = models.BigIntegerField(
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Discord user ID (snowflake) if linked",
    )
    discord_username = models.CharField(
        max_length=100,
        blank=True,
        help_text="Discord username (not guaranteed unique)",
    )

    # Audit fields
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "person_person"
        verbose_name = "Person"
        verbose_name_plural = "People"
        ordering = ["authentik_username"]

    def __str__(self) -> str:
        return f"{self.authentik_username}"

    def get_display_name(self) -> str:
        """Return best available display name."""
        return self.authentik_username or self.user.username

    def has_group(self, group_name: str) -> bool:
        """Check if user is in a specific Authentik group."""
        return group_name in self.authentik_groups

    def has_any_group(self, group_names: list[str]) -> bool:
        """Check if user is in any of the specified groups."""
        return any(group in self.authentik_groups for group in group_names)

    def is_gold_team(self) -> bool:
        """Check if user is in GoldTeam (operations)."""
        return self.has_group("WCComps_GoldTeam")

    def is_white_team(self) -> bool:
        """Check if user is in WhiteTeam."""
        return self.has_group("WCComps_WhiteTeam")

    def is_red_team(self) -> bool:
        """Check if user is in RedTeam."""
        return self.has_group("WCComps_RedTeam")

    def is_orange_team(self) -> bool:
        """Check if user is in OrangeTeam."""
        return self.has_group("WCComps_OrangeTeam")

    def is_black_team(self) -> bool:
        """Check if user is in BlackTeam."""
        return self.has_group("WCComps_BlackTeam")

    def is_staff_team(self) -> bool:
        """Check if user is in any staff team (Gold/White/Red/Orange/Black)."""
        return self.has_any_group(
            [
                "WCComps_GoldTeam",
                "WCComps_WhiteTeam",
                "WCComps_RedTeam",
                "WCComps_OrangeTeam",
                "WCComps_BlackTeam",
            ]
        )

    def get_team_number(self) -> int | None:
        """Extract team number from BlueTeam groups (BlueTeam_01 to BlueTeam_50)."""
        for group in self.authentik_groups:
            if group.startswith("WCComps_BlueTeam_"):
                try:
                    return int(group.split("_")[-1])
                except (ValueError, IndexError):
                    continue
        return None

    def is_blue_team(self) -> bool:
        """Check if user is in a BlueTeam."""
        return self.get_team_number() is not None

    def refresh_from_authentik(self) -> None:
        """
        Refresh cached Authentik data from SocialAccount.

        Should be called periodically or when user data changes.
        """
        from allauth.socialaccount.models import SocialAccount
        from core.utils import get_authentik_data

        try:
            username, groups, user_id = get_authentik_data(self.user)
            self.authentik_username = username
            self.authentik_groups = groups
            if user_id:
                self.authentik_user_id = user_id
            self.save()
        except SocialAccount.DoesNotExist:
            pass


@receiver(post_save, sender=User)
def create_or_update_person(sender, instance, created, **kwargs):
    """
    Automatically create/update Person when User is created/updated.

    This ensures every User has a corresponding Person profile.
    """
    if created:
        # Create Person for new User
        Person.objects.create(
            user=instance,
            authentik_username=instance.username,
        )
    else:
        # Update existing Person if it exists
        if hasattr(instance, "person"):
            # Trigger update timestamp
            instance.person.save()
