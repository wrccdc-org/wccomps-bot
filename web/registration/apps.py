"""App configuration for registration."""

from django.apps import AppConfig


class RegistrationConfig(AppConfig):
    """Configuration for registration app."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "registration"
