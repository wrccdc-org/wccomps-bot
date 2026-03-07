"""Database models for WCComps ticket system."""

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class UserGroups(models.Model):
    """
    Stores Authentik groups for a user. Refreshed on every login.

    This is the single source of truth for user permissions.
    Replaces allauth SocialAccount for group storage.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, primary_key=True)
    authentik_id = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        help_text="Authentik user UUID (sub claim)",
    )
    groups = models.JSONField(
        default=list,
        help_text="List of Authentik group names",
    )

    class Meta:
        verbose_name = "User Groups"
        verbose_name_plural = "User Groups"

    def __str__(self) -> str:
        return f"{self.user.username} ({len(self.groups)} groups)"


class AuditLog(models.Model):
    """General audit log for admin actions."""

    action = models.CharField(max_length=50)
    admin_user = models.CharField(max_length=255)
    target_entity = models.CharField(max_length=50)
    target_id = models.BigIntegerField()
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.action} by {self.admin_user}"


class DiscordTask(models.Model):
    """Task queue for Discord API operations (rate limit resilience).

    Payload schemas by task_type:
        create_thread:           {"ticket_id": int, "ticket_number": str, "team_number": int, "category": str, "title": str}
        update_embed:            {"ticket_id": int}
        update_dashboard:        {}
        archive_thread:          {"ticket_id": int}
        send_message:            {"channel_id": int, "message": str}
        post_comment:            {"ticket_id": int, "comment": str, "author": str}
        broadcast_message:       {"target": str, "message": str, "sender": str}
        assign_role:             {"discord_id": int, "team_number": int}
        assign_group_roles:      {"discord_id": int, "authentik_groups": list[str]}
        remove_role:             {"discord_id": int, "team_number": int}
        setup_team_infrastructure: {"team_number": int}
        log_to_channel:          {"message": str}
        post_ticket_update:      {"ticket_id": int, "action": str, "actor": str, "details": str}
        ticket_created_web:      {"ticket_id": int, "ticket_number": str, "team_number": int, "category": str, "title": str, "created_by": str}
        sync_roles:              {"requested_by": str, "dry_run": bool}
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("processing", "Processing"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    TASK_TYPE_CHOICES = [
        ("create_thread", "Create Thread"),
        ("update_embed", "Update Embed"),
        ("update_dashboard", "Update Dashboard"),
        ("archive_thread", "Archive Thread"),
        ("send_message", "Send Message"),
        ("post_comment", "Post Comment to Thread"),
        ("broadcast_message", "Broadcast Message"),
        ("assign_role", "Assign Team Role"),
        ("assign_group_roles", "Assign Group-Based Roles"),
        ("remove_role", "Remove Team Role"),
        ("setup_team_infrastructure", "Setup Team Infrastructure"),
        ("log_to_channel", "Log to Ops Channel"),
        ("post_ticket_update", "Post Ticket Update to Thread"),
        ("ticket_created_web", "Ticket Created via Web"),
        ("sync_roles", "Sync Roles Between Guilds"),
    ]

    task_type = models.CharField(max_length=50, choices=TASK_TYPE_CHOICES)
    ticket = models.ForeignKey("ticketing.Ticket", null=True, blank=True, on_delete=models.CASCADE)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=5)
    next_retry_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "next_retry_at"]),
            models.Index(fields=["task_type", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.task_type} ({self.status})"


class BotState(models.Model):
    """Bot state storage (dashboard message IDs, etc)."""

    key = models.CharField(max_length=100, unique=True)
    value = models.CharField(max_length=255)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.key}: {self.value}"


class DashboardUpdate(models.Model):
    """Dashboard update tracking (for debouncing)."""

    needs_update = models.BooleanField(default=True)
    last_updated = models.DateTimeField(auto_now=True)
    update_scheduled_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"Dashboard (needs_update={self.needs_update})"


class QueuedAnnouncement(models.Model):
    """Announcements queued for teams that don't have channels yet."""

    team = models.ForeignKey("team.Team", on_delete=models.CASCADE, related_name="queued_announcements")
    message = models.TextField()
    sender_name = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self) -> str:
        status = "delivered" if self.delivered_at else "pending"
        return f"Announcement for Team {self.team.team_number} ({status})"


class CompetitionConfig(models.Model):
    """Competition configuration and timing."""

    # Team settings
    max_team_members = models.IntegerField(default=10, help_text="Maximum members per team")

    # Competition timing
    competition_start_time = models.DateTimeField(
        null=True, blank=True, help_text="When applications should be enabled"
    )
    competition_end_time = models.DateTimeField(null=True, blank=True, help_text="When applications should be disabled")
    applications_enabled = models.BooleanField(default=False, help_text="Whether applications are currently enabled")

    # Application slugs to control
    controlled_applications = models.JSONField(
        default=list,
        help_text="List of Authentik application slugs to enable/disable (e.g., ['scoring', 'quotient2', 'semaphore'])",
    )

    # Audit
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_check = models.DateTimeField(null=True, blank=True, help_text="Last time background task checked")

    # Status channel
    status_channel_id = models.BigIntegerField(
        null=True, blank=True, help_text="Discord channel ID for competition status display"
    )
    status_message_id = models.BigIntegerField(
        null=True, blank=True, help_text="Discord message ID for status embed (updated in place)"
    )

    class Meta:
        verbose_name = "Competition Configuration"
        verbose_name_plural = "Competition Configuration"

    def __str__(self) -> str:
        if self.competition_start_time:
            return f"Competition starts at {self.competition_start_time} (enabled={self.applications_enabled})"
        return "Competition not scheduled"

    def should_enable_applications(self) -> bool:
        """Check if applications should be enabled based on current time."""
        if not self.competition_start_time:
            return False
        now = timezone.now()
        after_start = now >= self.competition_start_time
        before_end = self.competition_end_time is None or now < self.competition_end_time
        return after_start and before_end and not self.applications_enabled

    def should_disable_applications(self) -> bool:
        """Check if applications should be disabled based on current time."""
        if not self.competition_end_time:
            return False
        return timezone.now() >= self.competition_end_time and self.applications_enabled

    def ensure_controlled_applications(self) -> None:
        """Populate controlled_applications from Authentik if empty (only apps with BlueTeam bindings)."""
        if not self.controlled_applications:
            from core.authentik_manager import AuthentikManager

            self.controlled_applications = AuthentikManager().list_blueteam_applications()

    @classmethod
    def get_config(cls) -> "CompetitionConfig":
        """Get or create singleton config instance."""
        config, _ = cls.objects.get_or_create(pk=1)
        return config
