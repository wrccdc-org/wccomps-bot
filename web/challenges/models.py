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
