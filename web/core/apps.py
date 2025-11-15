from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self) -> None:
        """Import signals when app is ready."""
        from . import signals

        # Ensure signals module is loaded (reference it to prevent removal by linter)
        _ = signals
