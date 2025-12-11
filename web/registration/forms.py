"""Forms for team registration."""

from django import forms

from .models import Event, RegistrationContact, Season, TeamRegistration


class SchoolInfoForm(forms.ModelForm[TeamRegistration]):
    """Form for school information (step 1)."""

    class Meta:
        model = TeamRegistration
        fields = ["school_name"]
        labels = {
            "school_name": "School Name",
        }


class ContactForm(forms.ModelForm[RegistrationContact]):
    """Base form for contact information."""

    class Meta:
        model = RegistrationContact
        fields = ["name", "email", "phone"]
        labels = {
            "name": "Full Name",
            "email": "Email Address",
            "phone": "Phone Number",
        }


class CaptainContactForm(ContactForm):
    """Form for team captain contact (required)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.fields["name"].required = True
        self.fields["email"].required = True
        self.fields["phone"].required = True


class CoachContactForm(ContactForm):
    """Form for coach/faculty advisor contact (required)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.fields["name"].required = True
        self.fields["email"].required = True
        self.fields["phone"].required = False


class OptionalContactForm(ContactForm):
    """Form for optional contacts (co-captain, site judge)."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        for field in self.fields.values():
            field.required = False

    def has_data(self) -> bool:
        """Check if any data was provided."""
        if not self.is_bound:
            return False
        return bool(self.data.get(f"{self.prefix}-name") or self.data.get(f"{self.prefix}-email"))


class EventSelectionForm(forms.Form):
    """Form for selecting events to register for."""

    events = forms.ModelMultipleChoiceField(
        queryset=Event.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Select Events",
        help_text="Choose which events your team will participate in.",
    )

    def __init__(self, *args: object, season: Season | None = None, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        events_field = self.fields["events"]
        if isinstance(events_field, forms.ModelMultipleChoiceField):
            if season:
                events_field.queryset = Event.objects.filter(
                    season=season,
                    registration_open=True,
                ).order_by("date")
            else:
                events_field.queryset = Event.objects.filter(
                    season__is_active=True,
                    registration_open=True,
                ).order_by("date")


class RegistrationForm(forms.ModelForm[TeamRegistration]):
    """Combined form for simple registration."""

    contact_name = forms.CharField(max_length=255, label="Contact Name")
    contact_email = forms.EmailField(label="Contact Email")
    phone = forms.CharField(max_length=50, label="Phone Number")

    class Meta:
        model = TeamRegistration
        fields = ["school_name"]
        labels = {
            "school_name": "School Name",
        }

    def save(self, commit: bool = True) -> TeamRegistration:
        """Save registration and create captain contact."""
        registration = super().save(commit=commit)
        if commit:
            RegistrationContact.objects.update_or_create(
                registration=registration,
                role="captain",
                defaults={
                    "name": self.cleaned_data["contact_name"],
                    "email": self.cleaned_data["contact_email"],
                    "phone": self.cleaned_data["phone"],
                },
            )
        return registration


class SeasonForm(forms.ModelForm[Season]):
    """Form for creating/editing seasons."""

    class Meta:
        model = Season
        fields = ["name", "year", "is_active"]
        labels = {
            "name": "Season Name",
            "year": "Year",
            "is_active": "Active Season",
        }
        help_texts = {
            "is_active": "Only one season should be active at a time.",
        }


class EventForm(forms.ModelForm[Event]):
    """Form for creating/editing events."""

    class Meta:
        model = Event
        fields = [
            "name",
            "event_type",
            "event_number",
            "date",
            "start_time",
            "end_time",
            "registration_open",
            "registration_deadline",
            "max_teams",
        ]
        labels = {
            "name": "Event Name",
            "event_type": "Event Type",
            "event_number": "Event Number",
            "date": "Event Date",
            "start_time": "Start Time",
            "end_time": "End Time",
            "registration_open": "Registration Open",
            "registration_deadline": "Registration Deadline",
            "max_teams": "Maximum Teams",
        }
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}),
            "end_time": forms.TimeInput(attrs={"type": "time"}),
            "registration_deadline": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
