"""Competition configuration services."""

from core.models import CompetitionConfig


def ensure_controlled_applications(config: CompetitionConfig) -> None:
    """Fetch and cache Authentik application slugs if not already populated."""
    if config.controlled_applications:
        return
    from core.authentik_manager import AuthentikManager

    manager = AuthentikManager()
    slugs = manager.list_blueteam_applications()
    if slugs:
        config.controlled_applications = slugs
        config.save(update_fields=["controlled_applications"])
