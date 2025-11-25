"""Forms for scoring system."""

from decimal import Decimal
from typing import Any, cast

from django import forms
from django.db.models import QuerySet

from team.models import Team

from .models import (
    BlackTeamAdjustment,
    IncidentReport,
    InjectGrade,
    OrangeTeamBonus,
    RedTeamFinding,
    ScoringTemplate,
)
from .quotient_sync import get_box_choices, get_service_choices


class RedTeamFindingForm(forms.ModelForm[RedTeamFinding]):
    """Form for red team to submit vulnerability findings."""

    class Meta:
        model = RedTeamFinding
        fields = [
            "attack_vector",
            "source_ip",
            "affected_box",
            "affected_service",
            "destination_ip_template",
            "universally_attempted",
            "persistence_established",
            "affected_teams",
            "notes",
        ]
        widgets = {
            "attack_vector": forms.Textarea(
                attrs={
                    "rows": 5,
                    "placeholder": (
                        "e.g., 'Default Credentials', 'SSH default user', 'Web Portal Standard', 'RCE Service'..."
                    ),
                    "class": "form-control",
                }
            ),
            "affected_teams": forms.CheckboxSelectMultiple(),
            "notes": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Additional notes, remediation steps, or context",
                    "class": "form-control",
                }
            ),
            "destination_ip_template": forms.TextInput(attrs={"readonly": "readonly", "class": "form-control"}),
            "source_ip": forms.TextInput(attrs={"placeholder": "e.g., 10.0.0.5", "class": "form-control"}),
        }
        labels = {
            "attack_vector": "Attack Description",
            "source_ip": "Red Team Source IP",
            "affected_box": "Affected Box",
            "affected_service": "Affected Service",
            "destination_ip_template": "Target IP Template (auto-populated)",
            "universally_attempted": "Attempted against all teams",
            "persistence_established": "Persistence established",
            "affected_teams": "Affected Teams (select all that apply)",
            "notes": "Additional Notes",
        }
        help_texts = {
            "attack_vector": (
                "Provide a detailed description of the vulnerability exploited or attack performed. "
                "Start typing to see suggestions from previous submissions."
            ),
            "source_ip": "The IP address you attacked from.",
            "universally_attempted": "Check if this attack was attempted against all teams.",
            "persistence_established": "Check if you established persistent access.",
            "affected_teams": "Select all teams that were successfully compromised.",
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        # Populate dropdowns from Quotient metadata
        box_choices = get_box_choices()
        service_choices = get_service_choices()

        # If Quotient metadata is available, use dropdowns; otherwise use text inputs
        if box_choices:
            self.fields["affected_box"].widget = forms.Select(
                choices=[("", "Select a box...")] + box_choices, attrs={"class": "form-select"}
            )
        else:
            # Fallback to text input if Quotient metadata not available
            self.fields["affected_box"].widget = forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g., web-server, mail-server"}
            )
            self.fields["affected_box"].help_text = "Quotient metadata not synced - enter box name manually"

        if service_choices:
            self.fields["affected_service"].widget = forms.Select(
                choices=[("", "Select a service...")] + service_choices, attrs={"class": "form-select"}
            )
        else:
            # Fallback to text input if Quotient metadata not available
            self.fields["affected_service"].widget = forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g., SSH, HTTP, DNS"}
            )
            self.fields["affected_service"].help_text = "Quotient metadata not synced - enter service name manually"

        # Only show active teams
        affected_teams_field = cast("forms.ModelMultipleChoiceField[Team]", self.fields["affected_teams"])
        affected_teams_field.queryset = Team.objects.filter(is_active=True).order_by("team_number")


class IncidentReportForm(forms.ModelForm[IncidentReport]):
    """Form for blue teams to submit incident reports."""

    team = forms.ModelChoiceField(
        queryset=Team.objects.none(),
        required=False,
        help_text="Select team to submit on behalf of (admin only)",
    )

    class Meta:
        model = IncidentReport
        fields = [
            "attack_description",
            "source_ip",
            "destination_ip",
            "affected_box",
            "affected_service",
            "attack_detected_at",
            "attack_mitigated",
            "evidence_notes",
        ]
        widgets = {
            "attack_description": forms.Textarea(attrs={"rows": 4, "placeholder": "Describe what you detected"}),
            "attack_detected_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "evidence_notes": forms.Textarea(attrs={"rows": 3, "placeholder": "Additional evidence or notes"}),
            "destination_ip": forms.TextInput(attrs={"readonly": "readonly"}),
        }

    def __init__(self, team: Team | None = None, is_admin: bool = False, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        # Show team selector for admins only
        if is_admin:
            team_field = cast("forms.ModelChoiceField[Team]", self.fields["team"])
            team_field.queryset = Team.objects.filter(is_active=True).order_by("team_number")
            team_field.required = True
            if team:
                team_field.initial = team
        else:
            # Hide team field for regular users
            del self.fields["team"]

        # Populate dropdowns from Quotient metadata
        box_choices = get_box_choices()
        service_choices = get_service_choices()

        # If Quotient metadata is available, use dropdowns; otherwise use text inputs
        if box_choices:
            self.fields["affected_box"].widget = forms.Select(
                choices=[("", "---")] + box_choices, attrs={"class": "form-select"}
            )
        else:
            self.fields["affected_box"].widget = forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g., web-server, mail-server"}
            )
            self.fields["affected_box"].help_text = "Quotient metadata not synced - enter box name manually"

        if service_choices:
            self.fields["affected_service"].widget = forms.Select(
                choices=[("", "---")] + service_choices, attrs={"class": "form-select"}
            )
        else:
            self.fields["affected_service"].widget = forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g., SSH, HTTP, DNS"}
            )
            self.fields["affected_service"].help_text = "Quotient metadata not synced - enter service name manually"


class OrangeTeamBonusForm(forms.ModelForm[OrangeTeamBonus]):
    """Form for orange team to award bonus points."""

    class Meta:
        model = OrangeTeamBonus
        fields = ["team", "description", "points_awarded"]
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Describe why points are being awarded",
                }
            ),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Only show active teams
        team_field = cast("forms.ModelChoiceField[Team]", self.fields["team"])
        team_field.queryset = Team.objects.filter(is_active=True).order_by("team_number")


class InjectGradeForm(forms.ModelForm[InjectGrade]):
    """Form for white/gold team to grade inject submissions."""

    class Meta:
        model = InjectGrade
        fields = ["points_awarded", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 2, "placeholder": "Grader notes (optional)"}),
        }

    def __init__(self, max_points: Decimal | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        if max_points:
            self.fields["points_awarded"].widget.attrs["max"] = float(max_points)
            self.fields["points_awarded"].help_text = f"Maximum: {max_points} points"


class BulkInjectGradingForm(forms.Form):
    """Form for bulk inject grading (spreadsheet-style interface)."""

    def __init__(self, injects: list[dict[str, Any]], teams: list[Team], *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        # Create a field for each team-inject combination
        for inject in injects:
            for team in teams:
                field_name = f"inject_{inject['inject_id']}_team_{team.team_number}"
                self.fields[field_name] = forms.DecimalField(
                    required=False,
                    min_value=Decimal("0"),
                    max_value=inject["points"],
                    decimal_places=2,
                    widget=forms.NumberInput(
                        attrs={
                            "class": "inject-score-input",
                            "placeholder": "0",
                            "data-inject": inject["inject_id"],
                            "data-team": team.team_number,
                        }
                    ),
                )


class IncidentMatchForm(forms.ModelForm[IncidentReport]):
    """Form for gold team to match incident reports to red team findings."""

    class Meta:
        model = IncidentReport
        fields = [
            "matched_to_red_finding",
            "points_returned",
            "reviewer_notes",
        ]
        widgets = {
            "reviewer_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, suggested_findings: QuerySet[RedTeamFinding] | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

        if suggested_findings:
            # Limit choices to suggested findings
            matched_field = cast("forms.ModelChoiceField[RedTeamFinding]", self.fields["matched_to_red_finding"])
            matched_field.queryset = suggested_findings
            matched_field.empty_label = "No match / Manual points"


class ScoringTemplateForm(forms.ModelForm[ScoringTemplate]):
    """Form for configuring scoring multipliers."""

    class Meta:
        model = ScoringTemplate
        fields = [
            "inject_multiplier",
            "orange_multiplier",
        ]
        help_texts = {
            "inject_multiplier": "Multiplier applied to inject scores (e.g., 1.4 = 140%)",
            "orange_multiplier": "Multiplier applied to orange team scores (e.g., 5.5 = 550%)",
        }


class BlackTeamAdjustmentForm(forms.ModelForm[BlackTeamAdjustment]):
    """Form for manual point adjustments."""

    class Meta:
        model = BlackTeamAdjustment
        fields = ["team", "reason", "point_adjustment"]
        widgets = {
            "reason": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        team_field = cast("forms.ModelChoiceField[Team]", self.fields["team"])
        team_field.queryset = Team.objects.filter(is_active=True).order_by("team_number")
