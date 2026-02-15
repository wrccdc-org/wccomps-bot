"""Ticket categories — DB-backed helpers.

All functions return the same TicketCategoryConfig TypedDict shape
that the old hardcoded dict used, so consumer changes are mechanical.
"""

from typing import TypedDict

from ticketing.models import TicketCategory


class TicketCategoryConfig(TypedDict, total=False):
    display_name: str
    points: int
    required_fields: list[str]
    optional_fields: list[str]
    variable_cost_note: str
    variable_points: bool
    min_points: int
    max_points: int
    user_creatable: bool


def _model_to_config(cat: TicketCategory) -> TicketCategoryConfig:
    """Convert a TicketCategory model instance to a config dict."""
    config: TicketCategoryConfig = {
        "display_name": cat.display_name,
        "points": cat.points,
        "required_fields": cat.required_fields,
        "optional_fields": cat.optional_fields,
        "variable_points": cat.variable_points,
        "user_creatable": cat.user_creatable,
    }
    if cat.variable_cost_note:
        config["variable_cost_note"] = cat.variable_cost_note
    if cat.min_points:
        config["min_points"] = cat.min_points
    if cat.max_points:
        config["max_points"] = cat.max_points
    return config


def get_category_config(category_id: int | None) -> TicketCategoryConfig | None:
    """Get config dict for a single category by PK."""
    if category_id is None:
        return None
    try:
        cat = TicketCategory.objects.get(pk=category_id)
    except TicketCategory.DoesNotExist:
        return None
    return _model_to_config(cat)


def get_all_categories(
    user_creatable_only: bool = False,
) -> dict[int, TicketCategoryConfig]:
    """Get all categories as a dict keyed by PK."""
    qs = TicketCategory.objects.all()
    if user_creatable_only:
        qs = qs.filter(user_creatable=True)
    return {cat.pk: _model_to_config(cat) for cat in qs}
