"""Tests for registration forms."""

import pytest

from ..forms import (
    CaptainContactForm,
    CoachContactForm,
    EventSelectionForm,
    OptionalContactForm,
    RegistrationForm,
    SchoolInfoForm,
)
from ..models import Event, Season

pytestmark = pytest.mark.django_db


class TestSchoolInfoForm:
    """Test SchoolInfoForm validation."""

    def test_accepts_valid_data(self):
        """Form should accept valid school name."""
        form = SchoolInfoForm(data={"school_name": "Test High School"})
        assert form.is_valid()

    def test_rejects_empty_school_name(self):
        """Form should reject empty school name."""
        form = SchoolInfoForm(data={"school_name": ""})
        assert not form.is_valid()
        assert "school_name" in form.errors


class TestCaptainContactForm:
    """Test CaptainContactForm validation."""

    def test_accepts_valid_data(self):
        """Form should accept valid captain data."""
        form = CaptainContactForm(
            data={
                "name": "John Doe",
                "email": "john@example.com",
                "phone": "555-1234",
            }
        )
        assert form.is_valid()

    def test_rejects_missing_name(self):
        """Form should reject missing name."""
        form = CaptainContactForm(
            data={
                "name": "",
                "email": "john@example.com",
                "phone": "555-1234",
            }
        )
        assert not form.is_valid()
        assert "name" in form.errors

    def test_rejects_missing_email(self):
        """Form should reject missing email."""
        form = CaptainContactForm(
            data={
                "name": "John Doe",
                "email": "",
                "phone": "555-1234",
            }
        )
        assert not form.is_valid()
        assert "email" in form.errors

    def test_rejects_invalid_email(self):
        """Form should reject invalid email format."""
        form = CaptainContactForm(
            data={
                "name": "John Doe",
                "email": "not-an-email",
                "phone": "555-1234",
            }
        )
        assert not form.is_valid()
        assert "email" in form.errors

    def test_rejects_missing_phone(self):
        """Form should reject missing phone for captain."""
        form = CaptainContactForm(
            data={
                "name": "John Doe",
                "email": "john@example.com",
                "phone": "",
            }
        )
        assert not form.is_valid()
        assert "phone" in form.errors


class TestCoachContactForm:
    """Test CoachContactForm validation."""

    def test_accepts_valid_data(self):
        """Form should accept valid coach data."""
        form = CoachContactForm(
            data={
                "name": "Jane Smith",
                "email": "jane@example.com",
                "phone": "",
            }
        )
        assert form.is_valid()

    def test_rejects_missing_name(self):
        """Form should reject missing name."""
        form = CoachContactForm(
            data={
                "name": "",
                "email": "jane@example.com",
                "phone": "",
            }
        )
        assert not form.is_valid()
        assert "name" in form.errors

    def test_rejects_missing_email(self):
        """Form should reject missing email."""
        form = CoachContactForm(
            data={
                "name": "Jane Smith",
                "email": "",
                "phone": "",
            }
        )
        assert not form.is_valid()
        assert "email" in form.errors

    def test_phone_optional(self):
        """Phone should be optional for coach."""
        form = CoachContactForm(
            data={
                "name": "Jane Smith",
                "email": "jane@example.com",
            }
        )
        assert form.is_valid()


class TestOptionalContactForm:
    """Test OptionalContactForm validation."""

    def test_accepts_empty_data(self):
        """Form should accept empty data for optional contacts."""
        form = OptionalContactForm(data={})
        assert form.is_valid()

    def test_accepts_partial_data(self):
        """Form should accept partial data."""
        form = OptionalContactForm(
            data={
                "name": "Bob Wilson",
                "email": "",
                "phone": "",
            }
        )
        assert form.is_valid()

    def test_accepts_complete_data(self):
        """Form should accept complete data."""
        form = OptionalContactForm(
            data={
                "name": "Bob Wilson",
                "email": "bob@example.com",
                "phone": "555-5678",
            }
        )
        assert form.is_valid()

    def test_has_data_returns_false_for_empty(self):
        """has_data should return False for empty form."""
        form = OptionalContactForm(data={}, prefix="co_captain")
        assert not form.has_data()

    def test_has_data_returns_true_when_name_provided(self):
        """has_data should return True when name is provided."""
        form = OptionalContactForm(
            data={"co_captain-name": "Bob Wilson"},
            prefix="co_captain",
        )
        assert form.has_data()


class TestEventSelectionForm:
    """Test EventSelectionForm validation."""

    @pytest.fixture
    def active_season(self):
        """Create an active season."""
        return Season.objects.create(name="2026 Season", year=2026, is_active=True)

    @pytest.fixture
    def open_events(self, active_season):
        """Create open events."""
        from datetime import date

        return [
            Event.objects.create(
                season=active_season,
                name="Invitational #1",
                event_type="invitational",
                event_number=1,
                date=date(2026, 1, 15),
                registration_open=True,
            ),
            Event.objects.create(
                season=active_season,
                name="Invitational #2",
                event_type="invitational",
                event_number=2,
                date=date(2026, 2, 15),
                registration_open=True,
            ),
        ]

    def test_loads_open_events_from_active_season(self, open_events):
        """Form should load open events from active season."""
        form = EventSelectionForm()
        assert form.fields["events"].queryset.count() == 2

    def test_accepts_valid_event_selection(self, open_events):
        """Form should accept valid event selection."""
        form = EventSelectionForm(data={"events": [open_events[0].pk]})
        assert form.is_valid()

    def test_accepts_multiple_events(self, open_events):
        """Form should accept multiple event selection."""
        form = EventSelectionForm(data={"events": [e.pk for e in open_events]})
        assert form.is_valid()
        assert form.cleaned_data["events"].count() == 2

    def test_rejects_no_selection(self, open_events):
        """Form should reject no event selection."""
        form = EventSelectionForm(data={"events": []})
        assert not form.is_valid()
        assert "events" in form.errors


class TestRegistrationFormValidation:
    """Test RegistrationForm validation behavior."""

    @pytest.fixture
    def valid_form_data(self):
        """Valid form data for testing."""
        return {
            "school_name": "Test High School",
            "contact_name": "John Doe",
            "contact_email": "contact@example.com",
            "phone": "555-1234",
        }

    def test_form_accepts_valid_data(self, valid_form_data):
        """Form should accept valid data."""
        form = RegistrationForm(data=valid_form_data)
        assert form.is_valid()

    @pytest.mark.parametrize(
        "missing_field",
        ["school_name", "contact_name", "contact_email", "phone"],
    )
    def test_form_rejects_missing_required_field(self, valid_form_data, missing_field):
        """Form should reject data missing required fields."""
        del valid_form_data[missing_field]
        form = RegistrationForm(data=valid_form_data)
        assert not form.is_valid()
        assert missing_field in form.errors

    def test_form_rejects_invalid_email(self, valid_form_data):
        """Form should reject invalid email format."""
        valid_form_data["contact_email"] = "not-an-email"
        form = RegistrationForm(data=valid_form_data)
        assert not form.is_valid()
        assert "contact_email" in form.errors


class TestRegistrationFormSave:
    """Test RegistrationForm save behavior."""

    def test_form_creates_registration_with_pending_status(self):
        """Saved form should create registration with pending status."""
        form_data = {
            "school_name": "Test High School",
            "contact_name": "John Doe",
            "contact_email": "contact@example.com",
            "phone": "555-1234",
        }
        form = RegistrationForm(data=form_data)
        assert form.is_valid()
        registration = form.save()
        assert registration.pk is not None
        assert registration.status == "pending"

    def test_form_creates_captain_contact(self):
        """Saved form should create captain contact."""
        form_data = {
            "school_name": "Test High School",
            "contact_name": "John Doe",
            "contact_email": "contact@example.com",
            "phone": "555-1234",
        }
        form = RegistrationForm(data=form_data)
        assert form.is_valid()
        registration = form.save()

        captain = registration.contacts.get(role="captain")
        assert captain.name == "John Doe"
        assert captain.email == "contact@example.com"
        assert captain.phone == "555-1234"

    def test_registration_has_edit_token(self):
        """Saved registration should have an edit token."""
        form_data = {
            "school_name": "Test High School",
            "contact_name": "John Doe",
            "contact_email": "contact@example.com",
            "phone": "555-1234",
        }
        form = RegistrationForm(data=form_data)
        assert form.is_valid()
        registration = form.save()
        assert registration.edit_token
        assert len(registration.edit_token) > 32
