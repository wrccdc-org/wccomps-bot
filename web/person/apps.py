"""Person app configuration."""

from django.apps import AppConfig


class PersonConfig(AppConfig):
    """Configuration for person app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "person"

    def ready(self) -> None:
        """Import signals when app is ready."""
