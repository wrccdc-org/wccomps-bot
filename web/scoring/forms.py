"""Forms for scoring system."""

import ipaddress
from typing import cast

from django import forms
from django.contrib.auth.models import User
from django.db.models import QuerySet

from team.models import Team

from .models import (
    AttackType,
    IncidentReport,
    OrangeCheckType,
    OrangeTeamBonus,
    RedTeamFinding,
    RedTeamIPPool,
    ScoringTemplate,
)
from .quotient_sync import get_box_choices, get_service_choices


class RedTeamIPPoolForm(forms.ModelForm[RedTeamIPPool]):
    """Form for managing IP pools."""

    class Meta:
        model = RedTeamIPPool
        fields = ["name", "ip_addresses"]
        widgets = {
            "name": forms.TextInput(
                attrs={
                    "placeholder": "e.g., Rotation Pool A",
                    "class": "form-control",
                }
            ),
            "ip_addresses": forms.Textarea(
                attrs={
                    "rows": 10,
                    "placeholder": "Enter IP addresses, one per line or comma-separated:\n10.0.0.1\n10.0.0.2\n10.0.0.3",
                    "class": "form-control",
                }
            ),
        }
        labels = {
            "name": "Pool Name",
            "ip_addresses": "IP Addresses",
        }
        help_texts = {
            "name": "A memorable name for this pool of IPs",
            "ip_addresses": "Enter one IP per line or comma-separated. Invalid IPs will be rejected.",
        }

    def __init__(self, *args: object, user: User | None = None, **kwargs: object) -> None:
        self.user = user
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def clean_name(self) -> str:
        """Validate pool name is unique for this user."""
        name: str = self.cleaned_data["name"]
        if self.user:
            existing = RedTeamIPPool.objects.filter(name__iexact=name, created_by=self.user)
            if self.instance and self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            if existing.exists():
                raise forms.ValidationError("You already have a pool with this name")
        return name

    def clean_ip_addresses(self) -> str:
        """Validate and normalize IP addresses."""
        raw = self.cleaned_data["ip_addresses"]
        if not raw:
            raise forms.ValidationError("At least one IP address is required")

        # Parse IPs (split by newline and comma)
        valid_ips = []
        invalid_ips = []
        for line in raw.replace(",", "\n").split("\n"):
            ip = line.strip()
            if not ip:
                continue
            try:
                # Validate IP address format
                ipaddress.ip_address(ip)
                valid_ips.append(ip)
            except ValueError:
                invalid_ips.append(ip)

        if invalid_ips:
            raise forms.ValidationError(f"Invalid IP addresses: {', '.join(invalid_ips[:5])}")

        if not valid_ips:
            raise forms.ValidationError("At least one valid IP address is required")

        # Return normalized format (one per line)
        return "\n".join(valid_ips)


class RedTeamFindingForm(forms.ModelForm[RedTeamFinding]):
    """Form for red team to submit vulnerability findings."""

    # Radio button to choose between single IP or pool
    source_ip_type = forms.ChoiceField(
        choices=[
            ("single", "Single IP"),
            ("pool", "IP Pool"),
        ],
        initial="single",
        widget=forms.RadioSelect(attrs={"class": "form-check-input"}),
        label="Source IP Type",
    )

    # Text field for affected boxes (stored as JSON list)
    affected_boxes = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., web01, db01"}),
        label="Affected Boxes",
        help_text="Enter box names separated by commas",
    )

    class Meta:
        model = RedTeamFinding
        fields = [
            "attack_type",
            "source_ip",
            "source_ip_pool",
            "affected_service",
            "destination_ip_template",
            "universally_attempted",
            "persistence_established",
            # Outcome checkboxes for scoring
            "root_access",
            "user_access",
            "privilege_escalation",
            "credentials_recovered",
            "sensitive_files_recovered",
            "credit_cards_recovered",
            "pii_recovered",
            "encrypted_db_recovered",
            "db_decrypted",
            # Teams and notes
            "affected_teams",
            "notes",
        ]
        widgets = {
            "attack_type": forms.Select(attrs={"class": "form-select"}),
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
            "source_ip_pool": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "attack_type": "Attack Type",
            "source_ip": "Red Team Source IP",
            "source_ip_pool": "IP Pool",
            "affected_service": "Affected Service",
            "destination_ip_template": "Target IP Template (auto-populated)",
            "universally_attempted": "Attempted against all teams",
            "persistence_established": "Persistence established",
            "affected_teams": "Affected Teams (select all that apply)",
            "notes": "Description",
        }
        help_texts = {
            "attack_type": "Select the type of attack performed.",
            "source_ip": "The IP address you attacked from.",
            "source_ip_pool": "Select a pool of rotating IPs.",
            "universally_attempted": "Check if this attack was attempted against all teams.",
            "persistence_established": "Check if you established persistent access.",
            "affected_teams": "Select all teams that were successfully compromised.",
            "notes": "Full description of the attack and steps taken.",
        }

    def __init__(
        self, *args: object, team_count: int | None = None, user: User | None = None, **kwargs: object
    ) -> None:
        self.user = user
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

        # Configure attack_type field - only show active types
        attack_type_field = cast("forms.ModelChoiceField[AttackType]", self.fields["attack_type"])
        attack_type_field.queryset = AttackType.objects.filter(is_active=True)
        attack_type_field.empty_label = "Select attack type..."
        attack_type_field.required = True

        # Make source_ip and source_ip_pool not required at form level (validated in clean)
        self.fields["source_ip"].required = False
        self.fields["source_ip_pool"].required = False

        # Populate IP pool dropdown with user's pools only
        pool_field = cast("forms.ModelChoiceField[RedTeamIPPool]", self.fields["source_ip_pool"])
        if user:
            pool_field.queryset = RedTeamIPPool.objects.filter(created_by=user)
        else:
            pool_field.queryset = RedTeamIPPool.objects.none()
        pool_field.empty_label = "Select a pool..."

        # Store choices for template to display as suggestions
        self.box_choices = get_box_choices()
        self.service_choices = get_service_choices()

        # Set initial value for affected_boxes if editing (convert list to comma-separated)
        if self.instance and self.instance.pk and self.instance.affected_boxes:
            boxes = self.instance.affected_boxes
            self.initial["affected_boxes"] = boxes if isinstance(boxes, str) else ", ".join(boxes)

        # Service is optional - use text input for flexibility (suggestions shown in template)
        self.fields["affected_service"].widget = forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g., SSH, HTTP, DNS"}
        )

        # Only show active teams, limited by Quotient team count if available
        affected_teams_field = cast("forms.ModelMultipleChoiceField[Team]", self.fields["affected_teams"])
        queryset = Team.objects.filter(is_active=True).order_by("team_number")
        if team_count is not None:
            queryset = queryset.filter(team_number__lte=team_count)
        affected_teams_field.queryset = queryset

    def clean(self) -> dict[str, object]:
        """Validate that either source_ip or source_ip_pool is provided."""
        cleaned_data = super().clean() or {}
        source_ip_type = cleaned_data.get("source_ip_type")
        source_ip = cleaned_data.get("source_ip")
        source_ip_pool = cleaned_data.get("source_ip_pool")

        if source_ip_type == "single":
            if not source_ip:
                self.add_error("source_ip", "Source IP is required when using single IP mode")
            # Clear pool if single IP selected
            cleaned_data["source_ip_pool"] = None
        elif source_ip_type == "pool":
            if not source_ip_pool:
                self.add_error("source_ip_pool", "Please select an IP pool")
            # Clear single IP if pool selected
            cleaned_data["source_ip"] = None

        return cleaned_data

    def save(self, commit: bool = True) -> RedTeamFinding:
        """Save the form, including the affected_boxes field and auto-calculated points."""
        instance = super().save(commit=False)
        # Parse comma-separated box names into list
        boxes_str = self.cleaned_data.get("affected_boxes", "")
        if boxes_str:
            instance.affected_boxes = [b.strip() for b in boxes_str.split(",") if b.strip()]
        else:
            instance.affected_boxes = []
        # Auto-calculate points from outcome checkboxes
        instance.points_per_team = instance.calculate_points()
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class IncidentReportForm(forms.ModelForm[IncidentReport]):
    """Form for blue teams to submit incident reports."""

    team = forms.ModelChoiceField(
        queryset=Team.objects.none(),
        required=False,
        label="Team",
    )

    # Text field for affected boxes (stored as JSON list)
    affected_boxes = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., web01, db01"}),
        label="Affected Boxes",
        help_text="Enter box names separated by commas",
    )

    class Meta:
        model = IncidentReport
        fields = [
            "destination_ip",
            "affected_service",
            "source_ip",
            "attack_detected_at",
            "attack_description",
            "attack_mitigated",
        ]
        labels = {
            "destination_ip": "Affected IP",
            "affected_service": "Affected Service (optional)",
            "source_ip": "Attacker IP",
            "attack_detected_at": "When Detected",
            "attack_description": "What Happened",
            "attack_mitigated": "Attack Mitigated",
        }
        help_texts = {
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
                    "affected_boxes",
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

        # Service is optional - use text input for flexibility
        self.fields["affected_service"].required = False
        self.fields["affected_service"].widget = forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g., SSH, HTTP", "id": "id_affected_service"}
        )

        # Store choices for template to display as suggestions
        self.box_choices = get_box_choices()
        self.service_choices = get_service_choices()

        # Set initial value for affected_boxes if editing (convert list to comma-separated)
        if self.instance and self.instance.pk and self.instance.affected_boxes:
            boxes = self.instance.affected_boxes
            self.initial["affected_boxes"] = boxes if isinstance(boxes, str) else ", ".join(boxes)

    def save(self, commit: bool = True) -> IncidentReport:
        """Save the form, including the affected_boxes field."""
        instance = super().save(commit=False)
        # Parse comma-separated box names into list
        boxes_str = self.cleaned_data.get("affected_boxes", "")
        if boxes_str:
            instance.affected_boxes = [b.strip() for b in boxes_str.split(",") if b.strip()]
        else:
            instance.affected_boxes = []
        if commit:
            instance.save()
        return instance


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
    """Form for configuring scoring weights and max points.

    Four weighted categories (must sum to 100%):
    - Service: includes SLA penalties
    - Inject: inject/scenario responses
    - Orange: customer service adjustments
    - Red: red team deductions offset by incident recovery
    """

    class Meta:
        model = ScoringTemplate
        fields = [
            "service_weight",
            "inject_weight",
            "orange_weight",
            "red_weight",
            "service_max",
            "inject_max",
            "orange_max",
            "red_max",
        ]
        help_texts = {
            "service_weight": "Percentage weight for service uptime (includes SLA penalties)",
            "inject_weight": "Percentage weight for inject responses",
            "orange_weight": "Percentage weight for orange team adjustments",
            "red_weight": "Percentage weight for red team (deductions offset by recovery)",
            "service_max": "Maximum possible service points (from Quotient)",
            "inject_max": "Maximum possible inject points",
            "orange_max": "Maximum possible orange team points",
            "red_max": "Maximum possible red team deductions",
        }
        weight_attrs = {"min": "0", "max": "100", "step": "1", "class": "form-control weight-input"}
        max_attrs = {"min": "1", "step": "1", "class": "form-control"}
        widgets = {
            "service_weight": forms.NumberInput(attrs=weight_attrs),
            "inject_weight": forms.NumberInput(attrs=weight_attrs),
            "orange_weight": forms.NumberInput(attrs=weight_attrs),
            "red_weight": forms.NumberInput(attrs=weight_attrs),
            "service_max": forms.NumberInput(attrs=max_attrs),
            "inject_max": forms.NumberInput(attrs=max_attrs),
            "orange_max": forms.NumberInput(attrs=max_attrs),
            "red_max": forms.NumberInput(attrs=max_attrs),
        }
