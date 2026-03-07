"""Admin views package.

Re-exports all view functions so existing imports continue to work:
    from core import admin_views
    admin_views.admin_competition(...)
"""

from .broadcast import (
    admin_broadcast,
    admin_broadcast_action,
    admin_sync_roles,
    admin_sync_roles_action,
    admin_task_status,
)
from .categories import (
    admin_categories,
    admin_category_create,
    admin_category_delete,
    admin_category_edit,
)
from .competition import (
    admin_competition,
    admin_competition_action,
)
from .teams import (
    admin_team_action,
    admin_team_detail,
    admin_teams,
    admin_teams_bulk_action,
)

__all__ = [
    "admin_broadcast",
    "admin_broadcast_action",
    "admin_categories",
    "admin_category_create",
    "admin_category_delete",
    "admin_category_edit",
    "admin_competition",
    "admin_competition_action",
    "admin_sync_roles",
    "admin_sync_roles_action",
    "admin_task_status",
    "admin_team_action",
    "admin_team_detail",
    "admin_teams",
    "admin_teams_bulk_action",
]
