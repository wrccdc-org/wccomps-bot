"""Team management models."""

import logging
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


class Team(models.Model):
    """Competition team (1-50)."""

    team_number = models.IntegerField(unique=True)
    team_name = models.CharField(max_length=100)
    authentik_group = models.CharField(max_length=255, blank=True)

    # Discord integration
    discord_role_id = models.BigIntegerField(null=True, blank=True)
    discord_category_id = models.BigIntegerField(null=True, blank=True)

    # Limits
    max_members = models.IntegerField(default=10)

    # Ticket sequence counter
    ticket_counter = models.IntegerField(default=0)

    # Status
    is_active = models.BooleanField(default=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["team_number"]

    def __str__(self) -> str:
        return f"{self.team_name}"

    def clean(self) -> None:
        """Validate team constraints."""
        super().clean()

        # Auto-generate authentik_group if not provided
        if not self.authentik_group and self.team_number:
            self.authentik_group = f"WCComps_BlueTeam{self.team_number:02d}"

        # Validate team_number range (1-50)
        if self.team_number is not None:
            if self.team_number < 1 or self.team_number > 50:
                raise ValidationError(
                    {
                        "team_number": f"Team number must be between 1 and 50, got {self.team_number}"
                    }
                )

        # Validate max_members (must be positive)
        if self.max_members is not None:
            if self.max_members < 1:
                raise ValidationError(
                    {
                        "max_members": f"Team must have at least 1 member, got {self.max_members}"
                    }
                )

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Override save to run validation."""
        # Skip validation when using update_fields (e.g., with F() expressions)
        if not kwargs.get("update_fields"):
            self.full_clean()
        super().save(*args, **kwargs)

    def get_member_count(self) -> int:
        """Get count of active members."""
        return self.members.filter(is_active=True).count()

    def is_full(self) -> bool:
        """Check if team has reached max members."""
        return self.get_member_count() >= self.max_members


class DiscordLink(models.Model):
    """Link between Discord user and Authentik account (optionally part of a team)."""

    discord_id = models.BigIntegerField()
    discord_username = models.CharField(max_length=255)
    authentik_username = models.CharField(max_length=255)
    authentik_user_id = models.CharField(max_length=255)
    team = models.ForeignKey(
        Team, on_delete=models.CASCADE, related_name="members", null=True, blank=True
    )
    is_active = models.BooleanField(default=True)
    linked_at = models.DateTimeField(auto_now_add=True)
    unlinked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["discord_id", "is_active"]),
            models.Index(fields=["authentik_user_id", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["discord_id"],
                condition=models.Q(is_active=True),
                name="team_unique_active_discord_link",
            ),
            # Note: authentik_user_id is NOT unique because blue teams share a single
            # Authentik account (e.g., team01) but multiple Discord users link to it
        ]

    def __str__(self) -> str:
        if self.team:
            return f"{self.discord_username} → {self.team.team_name}"
        return f"{self.discord_username} → {self.authentik_username}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Override save to deactivate previous active link when creating new one."""
        if self.is_active:
            # Deactivate any existing active link for this discord_id
            # (one Discord user can only have one active link at a time)
            DiscordLink.objects.filter(
                discord_id=self.discord_id, is_active=True
            ).exclude(pk=self.pk).update(is_active=False, unlinked_at=timezone.now())

            # Do NOT deactivate links based on authentik_user_id because blue teams
            # share a single Authentik account (multiple Discord users -> same authentik_user_id)
        super().save(*args, **kwargs)


class LinkToken(models.Model):
    """Temporary token for linking flow."""

    token = models.CharField(max_length=64, unique=True)
    discord_id = models.BigIntegerField()
    discord_username = models.CharField(max_length=255)
    used = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["token", "used", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"Token for {self.discord_username}"

    def is_expired(self) -> bool:
        """Check if token has expired."""
        return timezone.now() > self.expires_at


class LinkAttempt(models.Model):
    """Audit log for link attempts."""

    discord_id = models.BigIntegerField()
    discord_username = models.CharField(max_length=255)
    authentik_username = models.CharField(max_length=255)
    team = models.ForeignKey(Team, null=True, blank=True, on_delete=models.SET_NULL)
    success = models.BooleanField()
    failure_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["-created_at"]),
        ]

    def __str__(self) -> str:
        status = "Success" if self.success else "Failed"
        return f"{self.discord_username} → {self.authentik_username} ({status})"


class LinkRateLimit(models.Model):
    """Rate limiting for link attempts (5 per hour per user)."""

    discord_id = models.BigIntegerField()
    attempted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["discord_id", "-attempted_at"]),
        ]

    def __str__(self) -> str:
        return f"Link attempt by {self.discord_id} at {self.attempted_at}"

    @classmethod
    def check_rate_limit(cls, discord_id: int) -> tuple[bool, int]:
        """
        Check if user has exceeded rate limit (5 attempts per hour).

        Returns: (is_allowed, attempts_in_last_hour)
        """
        from datetime import timedelta

        one_hour_ago = timezone.now() - timedelta(hours=1)

        # Count attempts in last hour
        recent_attempts = cls.objects.filter(
            discord_id=discord_id, attempted_at__gte=one_hour_ago
        ).count()

        return recent_attempts < 5, recent_attempts


class SchoolInfo(models.Model):
    """School information for teams (GoldTeam only)."""

    team = models.OneToOneField(
        Team, on_delete=models.CASCADE, related_name="school_info"
    )
    school_name = models.CharField(max_length=255)
    contact_email = models.EmailField()
    secondary_email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "School Information"
        verbose_name_plural = "School Information"
        ordering = ["team__team_number"]

    def __str__(self) -> str:
        return f"{self.school_name} (Team {self.team.team_number})"
