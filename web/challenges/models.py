from django.contrib.auth.models import User
from django.db import models


class OrangeCheckIn(models.Model):
    """Tracks orange team member availability during competition."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="orange_checkins")
    checked_in_at = models.DateTimeField(auto_now_add=True)
    checked_out_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "orange_checkin"
        ordering = ["-checked_in_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_active=True),
                name="one_active_checkin_per_user",
            ),
        ]

    def __str__(self) -> str:
        status = "IN" if self.is_active else "OUT"
        return f"{self.user.username} [{status}]"


class OrangeCheck(models.Model):
    """A check template with rubric criteria, created by a lead."""

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("scheduled", "Scheduled"),
        ("active", "Active"),
        ("closed", "Closed"),
    ]

    title = models.CharField(max_length=200)
    description = models.TextField(help_text="Steps/instructions for the orange teamer")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    scheduled_at = models.DateTimeField(null=True, blank=True, help_text="When assignments go live")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="created_checks")
    created_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "orange_check"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"[{self.status}] {self.title}"

    @property
    def max_score(self) -> int:
        return self.criteria.aggregate(total=models.Sum("points"))["total"] or 0


class OrangeCheckCriterion(models.Model):
    """A rubric line item for a check."""

    orange_check = models.ForeignKey(OrangeCheck, on_delete=models.CASCADE, related_name="criteria")
    label = models.CharField(max_length=200)
    points = models.PositiveIntegerField()
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "orange_check_criterion"
        ordering = ["sort_order", "id"]

    def __str__(self) -> str:
        return f"{self.label} ({self.points} pts)"
