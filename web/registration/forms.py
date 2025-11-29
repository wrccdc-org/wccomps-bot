"""Forms for team registration."""

from django import forms

from .models import TeamRegistration


class RegistrationForm(forms.ModelForm[TeamRegistration]):
    """Form for team registration."""

    class Meta:
        model = TeamRegistration
        fields = ["school_name", "contact_email", "phone"]
        labels = {
            "school_name": "School Name",
            "contact_email": "Contact Email",
            "phone": "Phone Number",
        }
