"""Person app models - User profiles with Authentik integration."""

import re
from typing import Any

from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


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
        max_length=64,
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

    # Student helper fields
    is_student_helper = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Whether this person is currently a student helper",
    )
    helper_role_name = models.CharField(
        max_length=100,
        blank=True,
        help_text='Discord role name (e.g., "UCI Invitationals 2026")',
    )
    helper_role_id = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="Discord role ID (snowflake)",
    )
    helper_activated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When helper access was granted",
    )
    helper_deactivated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When helper access was revoked",
    )
    helper_removal_reason = models.TextField(
        blank=True,
        help_text="Reason for helper access removal",
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

    def get_team_number(self) -> int | None:
        """Extract team number from BlueTeam groups (BlueTeam01 to BlueTeam50)."""
        for group in self.authentik_groups:
            match = re.match(r"^WCComps_BlueTeam(\d+)$", group)
            if match:
                return int(match.group(1))
        return None

    def is_blue_team(self) -> bool:
        """Check if user is in a BlueTeam."""
        return self.get_team_number() is not None

    def set_helper(self, role_name: str, role_id: int | None = None) -> None:
        """Grant student helper access."""
        self.is_student_helper = True
        self.helper_role_name = role_name
        if role_id is not None:
            self.helper_role_id = role_id
        self.helper_activated_at = timezone.now()
        self.helper_deactivated_at = None
        self.helper_removal_reason = ""
        self.save()

    def remove_helper(self, reason: str = "") -> None:
        """Revoke student helper access."""
        if self.is_student_helper:
            self.is_student_helper = False
            self.helper_deactivated_at = timezone.now()
            self.helper_removal_reason = reason
            self.save()

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
def create_or_update_person(sender: type[User], instance: User, created: bool, **kwargs: Any) -> None:
    """
    Automatically create/update Person when User is created/updated.

    This ensures every User has a corresponding Person profile.
    """
    if created:
        # Create Person for new User
        person = Person.objects.create(
            user=instance,
            authentik_username=instance.username,
        )
        # Populate Authentik groups from SocialAccount if available
        person.refresh_from_authentik()
    # Update existing Person if it exists
    elif hasattr(instance, "person"):
        # Trigger update timestamp
        instance.person.save()
