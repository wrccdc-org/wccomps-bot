"""Django forms for orange team challenge views."""

from typing import Any

from django import forms
from django.http import QueryDict


class OrangeCheckForm(forms.Form):
    title = forms.CharField(max_length=200)
    description = forms.CharField(required=False)
    scheduled_at = forms.CharField(required=False)


class CheckAssignForm(forms.Form):
    user_ids = forms.TypedMultipleChoiceField(coerce=int)

    def __init__(self, *args: Any, choices: list[tuple[int, str]] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if choices:
            self.fields["user_ids"].choices = choices


class FollowUpForm(forms.Form):
    assignment_id = forms.IntegerField()
    minutes = forms.IntegerField(initial=15)
    note = forms.CharField(required=False)


class AssignmentRejectForm(forms.Form):
    notes = forms.CharField(required=False)


def extract_criteria(post_data: QueryDict) -> list[dict[str, str | int]]:
    """Parse dynamic criterion_label_{i} / criterion_points_{i} fields.

    Enforces max_length=200 on labels (matches OrangeCheckCriterion.label).
    """
    criteria: list[dict[str, str | int]] = []
    i = 0
    while f"criterion_label_{i}" in post_data:
        label = post_data.get(f"criterion_label_{i}", "").strip()[:200]
        points_str = post_data.get(f"criterion_points_{i}", "").strip()
        if label and points_str:
            try:
                points = int(points_str)
                criteria.append({"label": label, "points": points, "sort_order": i})
            except ValueError:
                pass
        i += 1
    return criteria
