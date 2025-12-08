"""Forms for scoring system."""

from typing import cast

from django import forms
from django.db.models import QuerySet

from team.models import Team

from .models import (
    IncidentReport,
    OrangeCheckType,
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
            "attack_vector": forms.TextInput(
                attrs={
                    "placeholder": "e.g., Default Credentials, RCE, SQL Injection",
                    "class": "form-control",
                    "autocomplete": "off",
                }
            ),
            "affected_teams": forms.CheckboxSelectMultiple(),
            "notes": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Full description of the attack and steps taken...",
                    "class": "form-control",
                }
            ),
            "destination_ip_template": forms.TextInput(attrs={"readonly": "readonly", "class": "form-control"}),
            "source_ip": forms.TextInput(attrs={"placeholder": "e.g., 10.0.0.5", "class": "form-control"}),
        }
        labels = {
            "attack_vector": "Attack Type",
            "source_ip": "Red Team Source IP",
            "affected_box": "Affected Box",
            "affected_service": "Affected Service",
            "destination_ip_template": "Target IP Template (auto-populated)",
            "universally_attempted": "Attempted against all teams",
            "persistence_established": "Persistence established",
            "affected_teams": "Affected Teams (select all that apply)",
            "notes": "Description",
        }
        help_texts = {
            "attack_vector": "Short name for this attack (1-2 words). Start typing to see suggestions.",
            "source_ip": "The IP address you attacked from.",
            "universally_attempted": "Check if this attack was attempted against all teams.",
            "persistence_established": "Check if you established persistent access.",
            "affected_teams": "Select all teams that were successfully compromised.",
            "notes": "Full description of the attack and steps taken.",
        }

    def __init__(self, *args: object, team_count: int | None = None, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

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

        # Only show active teams, limited by Quotient team count if available
        affected_teams_field = cast("forms.ModelMultipleChoiceField[Team]", self.fields["affected_teams"])
        queryset = Team.objects.filter(is_active=True).order_by("team_number")
        if team_count is not None:
            queryset = queryset.filter(team_number__lte=team_count)
        affected_teams_field.queryset = queryset


class IncidentReportForm(forms.ModelForm[IncidentReport]):
    """Form for blue teams to submit incident reports."""

    team = forms.ModelChoiceField(
        queryset=Team.objects.none(),
        required=False,
        label="Team",
    )

    class Meta:
        model = IncidentReport
        fields = [
            "affected_box",
            "destination_ip",
            "affected_service",
            "source_ip",
            "attack_detected_at",
            "attack_description",
            "attack_mitigated",
        ]
        labels = {
            "affected_box": "Affected Box",
            "destination_ip": "Affected IP",
            "affected_service": "Affected Service (optional)",
            "source_ip": "Attacker IP",
            "attack_detected_at": "When Detected",
            "attack_description": "What Happened",
            "attack_mitigated": "Attack Mitigated",
        }
        help_texts = {
            "affected_box": "",
            "destination_ip": "",
            "affected_service": "",
            "source_ip": "",
            "attack_detected_at": "",
            "attack_description": "",
            "attack_mitigated": "Check if you've stopped the attack",
        }
        widgets = {
            "attack_description": forms.Textarea(attrs={"rows": 3}),
            "attack_detected_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "destination_ip": forms.TextInput(attrs={"readonly": "readonly"}),
        }

    def __init__(self, team: Team | None = None, is_admin: bool = False, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

        # Show team selector for admins only
        if is_admin:
            team_field = cast("forms.ModelChoiceField[Team]", self.fields["team"])
            team_field.queryset = Team.objects.filter(is_active=True).order_by("team_number")
            team_field.required = True
            team_field.widget.attrs["id"] = "id_team"
            if team:
                team_field.initial = team
            # Reorder fields to put team first
            self.order_fields(
                [
                    "team",
                    "affected_box",
                    "destination_ip",
                    "affected_service",
                    "source_ip",
                    "attack_detected_at",
                    "attack_description",
                    "attack_mitigated",
                ]
            )
        else:
            # Hide team field for regular users
            del self.fields["team"]

        # Populate dropdowns from Quotient metadata
        box_choices = get_box_choices()

        # Service is optional
        self.fields["affected_service"].required = False

        # If Quotient metadata is available, use dropdowns; otherwise use text inputs
        if box_choices:
            self.fields["affected_box"].widget = forms.Select(
                choices=[("", "---")] + box_choices,
                attrs={"class": "form-select", "id": "id_affected_box"},
            )
            # Service starts empty, populated by JavaScript based on box selection
            self.fields["affected_service"].widget = forms.Select(
                choices=[("", "(select box first)")],
                attrs={"class": "form-select", "id": "id_affected_service"},
            )
        else:
            self.fields["affected_box"].widget = forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g., web-server"}
            )
            self.fields["affected_service"].widget = forms.TextInput(
                attrs={"class": "form-control", "placeholder": "e.g., SSH, HTTP"}
            )


class OrangeTeamBonusForm(forms.ModelForm[OrangeTeamBonus]):
    """Form for orange team to award or deduct points."""

    class Meta:
        model = OrangeTeamBonus
        fields = ["team", "check_type", "description", "points_awarded"]
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 2,
                    "placeholder": "Additional notes (optional)",
                }
            ),
        }
        labels = {
            "check_type": "Check Type",
            "description": "Notes",
            "points_awarded": "Points",
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        # Only show active teams
        team_field = cast("forms.ModelChoiceField[Team]", self.fields["team"])
        team_field.queryset = Team.objects.filter(is_active=True).order_by("team_number")
        # Make check_type required, description optional
        self.fields["check_type"].required = True
        self.fields["description"].required = False


class OrangeCheckTypeForm(forms.ModelForm[OrangeCheckType]):
    """Form for managing orange check types."""

    class Meta:
        model = OrangeCheckType
        fields = ["name", "default_points"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "e.g., Customer service call"}),
        }
        labels = {
            "default_points": "Default Points",
        }
        help_texts = {
            "default_points": "Use negative for penalties",
        }


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

    def __init__(
        self, suggested_findings: QuerySet[RedTeamFinding] | None = None, *args: object, **kwargs: object
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

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
            "service_multiplier",
            "inject_multiplier",
            "orange_multiplier",
            "red_multiplier",
            "sla_multiplier",
            "recovery_multiplier",
        ]
        help_texts = {
            "service_multiplier": "Multiplier applied to service scores (e.g., 1.0 = 100%)",
            "inject_multiplier": "Multiplier applied to inject scores (e.g., 1.4 = 140%)",
            "orange_multiplier": "Multiplier applied to orange team scores (e.g., 5.5 = 550%)",
            "red_multiplier": "Multiplier applied to red team deductions (e.g., 1.0 = 100%)",
            "sla_multiplier": "Multiplier applied to SLA penalties (e.g., 1.0 = 100%)",
            "recovery_multiplier": "Multiplier applied to incident recovery points (e.g., 1.0 = 100%)",
        }
