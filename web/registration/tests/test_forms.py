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


@pytest.fixture
def active_season_with_event(db):
    """Create an active season with an open event."""
    season = Season.objects.create(name="2026 Season", year=2026, is_active=True)
    event = Event.objects.create(
        season=season,
        name="Invitational 1",
        event_type="invitational",
        event_number=1,
        date="2026-01-15",
        registration_open=True,
    )
    return season, event


class TestRegistrationFormValidation:
    """Test RegistrationForm validation behavior."""

    @pytest.fixture
    def valid_form_data(self, active_season_with_event):
        """Valid form data for testing."""
        _, event = active_season_with_event
        return {
            "school_name": "Test High School",
            "region": "wrccdc",
            "captain_name": "John Doe",
            "captain_email": "captain@example.com",
            "captain_phone": "555-1234",
            "coach_name": "Dr. Smith",
            "coach_email": "coach@example.com",
            "coach_phone": "",
            "events": [event.id],
            "agree_to_rules": True,
        }

    def test_form_accepts_valid_data(self, valid_form_data):
        """Form should accept valid data."""
        form = RegistrationForm(data=valid_form_data)
        assert form.is_valid(), form.errors

    @pytest.mark.parametrize(
        "missing_field",
        ["school_name", "captain_name", "captain_email", "captain_phone", "coach_name", "coach_email"],
    )
    def test_form_rejects_missing_required_field(self, valid_form_data, missing_field):
        """Form should reject data missing required fields."""
        del valid_form_data[missing_field]
        form = RegistrationForm(data=valid_form_data)
        assert not form.is_valid()
        assert missing_field in form.errors

    def test_form_rejects_invalid_captain_email(self, valid_form_data):
        """Form should reject invalid email format."""
        valid_form_data["captain_email"] = "not-an-email"
        form = RegistrationForm(data=valid_form_data)
        assert not form.is_valid()
        assert "captain_email" in form.errors

    def test_form_rejects_missing_events(self, valid_form_data):
        """Form should reject when no events selected."""
        valid_form_data["events"] = []
        form = RegistrationForm(data=valid_form_data)
        assert not form.is_valid()
        assert "events" in form.errors

    def test_form_rejects_missing_rules_agreement(self, valid_form_data):
        """Form should reject when rules not agreed to."""
        valid_form_data["agree_to_rules"] = False
        form = RegistrationForm(data=valid_form_data)
        assert not form.is_valid()
        assert "agree_to_rules" in form.errors


class TestRegistrationFormSave:
    """Test RegistrationForm save behavior."""

    @pytest.fixture
    def valid_form_data(self, active_season_with_event):
        """Valid form data for testing."""
        _, event = active_season_with_event
        return {
            "school_name": "Test High School",
            "region": "wrccdc",
            "captain_name": "John Doe",
            "captain_email": "captain@example.com",
            "captain_phone": "555-1234",
            "coach_name": "Dr. Smith",
            "coach_email": "coach@example.com",
            "coach_phone": "555-5678",
            "events": [event.id],
            "agree_to_rules": True,
        }

    def test_form_creates_registration_with_pending_status(self, valid_form_data):
        """Saved form should create registration with pending status."""
        form = RegistrationForm(data=valid_form_data)
        assert form.is_valid(), form.errors
        registration = form.save()
        assert registration.pk is not None
        assert registration.status == "pending"

    def test_form_creates_captain_contact(self, valid_form_data):
        """Saved form should create captain contact."""
        form = RegistrationForm(data=valid_form_data)
        assert form.is_valid(), form.errors
        registration = form.save()

        captain = registration.contacts.get(role="captain")
        assert captain.name == "John Doe"
        assert captain.email == "captain@example.com"
        assert captain.phone == "555-1234"

    def test_form_creates_coach_contact(self, valid_form_data):
        """Saved form should create coach contact."""
        form = RegistrationForm(data=valid_form_data)
        assert form.is_valid(), form.errors
        registration = form.save()

        coach = registration.contacts.get(role="coach")
        assert coach.name == "Dr. Smith"
        assert coach.email == "coach@example.com"
        assert coach.phone == "555-5678"

    def test_form_creates_event_enrollments(self, valid_form_data, active_season_with_event):
        """Saved form should create event enrollments."""
        _, event = active_season_with_event
        form = RegistrationForm(data=valid_form_data)
        assert form.is_valid(), form.errors
        registration = form.save()

        enrollments = registration.event_enrollments.all()
        assert enrollments.count() == 1
        assert enrollments.first().event == event

    def test_registration_has_edit_token(self, valid_form_data):
        """Saved registration should have an edit token."""
        form = RegistrationForm(data=valid_form_data)
        assert form.is_valid(), form.errors
        registration = form.save()
        assert registration.edit_token
        assert len(registration.edit_token) > 32


class TestRegistrationFormRegionValidation:
    """Test RegistrationForm region validation behavior."""

    @pytest.fixture
    def season_with_events(self, db):
        """Create a season with invitational, qualifier, and regional events."""
        from datetime import date

        season = Season.objects.create(name="2026 Season", year=2026, is_active=True)
        invitational = Event.objects.create(
            season=season,
            name="Invitational 1",
            event_type="invitational",
            event_number=1,
            date=date(2026, 1, 15),
            registration_open=True,
        )
        qualifier = Event.objects.create(
            season=season,
            name="Qualifier 1",
            event_type="qualifier",
            event_number=1,
            date=date(2026, 2, 15),
            registration_open=True,
        )
        regional = Event.objects.create(
            season=season,
            name="Regional",
            event_type="regional",
            event_number=1,
            date=date(2026, 3, 15),
            registration_open=True,
        )
        return season, invitational, qualifier, regional

    @pytest.fixture
    def base_form_data(self):
        """Base form data without events."""
        return {
            "school_name": "Test High School",
            "captain_name": "John Doe",
            "captain_email": "captain@example.com",
            "captain_phone": "555-1234",
            "coach_name": "Dr. Smith",
            "coach_email": "coach@example.com",
            "coach_phone": "",
            "agree_to_rules": True,
        }

    def test_wrccdc_can_register_for_qualifier(self, base_form_data, season_with_events):
        """WRCCDC teams can register for qualifiers."""
        _, _, qualifier, _ = season_with_events
        base_form_data["region"] = "wrccdc"
        base_form_data["events"] = [qualifier.id]
        form = RegistrationForm(data=base_form_data)
        assert form.is_valid(), form.errors

    def test_wrccdc_can_register_for_regional(self, base_form_data, season_with_events):
        """WRCCDC teams can register for regionals."""
        _, _, _, regional = season_with_events
        base_form_data["region"] = "wrccdc"
        base_form_data["events"] = [regional.id]
        form = RegistrationForm(data=base_form_data)
        assert form.is_valid(), form.errors

    def test_non_wrccdc_can_register_for_invitational(self, base_form_data, season_with_events):
        """Non-WRCCDC teams can register for invitationals."""
        _, invitational, _, _ = season_with_events
        base_form_data["region"] = "mwccdc"
        base_form_data["events"] = [invitational.id]
        form = RegistrationForm(data=base_form_data)
        assert form.is_valid(), form.errors

    def test_non_wrccdc_blocked_from_qualifier(self, base_form_data, season_with_events):
        """Non-WRCCDC teams cannot register for qualifiers."""
        _, _, qualifier, _ = season_with_events
        base_form_data["region"] = "mwccdc"
        base_form_data["events"] = [qualifier.id]
        form = RegistrationForm(data=base_form_data)
        assert not form.is_valid()
        assert "__all__" in form.errors
        assert "Only Western Regional (WRCCDC) teams" in str(form.errors["__all__"])

    def test_non_wrccdc_blocked_from_regional(self, base_form_data, season_with_events):
        """Non-WRCCDC teams cannot register for regionals."""
        _, _, _, regional = season_with_events
        base_form_data["region"] = "neccdc"
        base_form_data["events"] = [regional.id]
        form = RegistrationForm(data=base_form_data)
        assert not form.is_valid()
        assert "__all__" in form.errors
        assert "Only Western Regional (WRCCDC) teams" in str(form.errors["__all__"])

    def test_non_wrccdc_blocked_mixed_events(self, base_form_data, season_with_events):
        """Non-WRCCDC teams cannot register for mix of invitational and qualifier."""
        _, invitational, qualifier, _ = season_with_events
        base_form_data["region"] = "seccdc"
        base_form_data["events"] = [invitational.id, qualifier.id]
        form = RegistrationForm(data=base_form_data)
        assert not form.is_valid()
        assert "__all__" in form.errors
        assert "Qualifier 1" in str(form.errors["__all__"])

    def test_at_large_blocked_from_qualifier(self, base_form_data, season_with_events):
        """At-large teams cannot register for qualifiers."""
        _, _, qualifier, _ = season_with_events
        base_form_data["region"] = "at_large"
        base_form_data["events"] = [qualifier.id]
        form = RegistrationForm(data=base_form_data)
        assert not form.is_valid()
        assert "__all__" in form.errors
