"""Tests for registration forms."""

import pytest

from ..forms import RegistrationForm

pytestmark = pytest.mark.django_db


class TestRegistrationFormValidation:
    """Test RegistrationForm validation behavior."""

    @pytest.fixture
    def valid_form_data(self):
        """Valid form data for testing."""
        return {
            "school_name": "Test High School",
            "contact_email": "contact@example.com",
            "phone": "555-1234",
        }

    def test_form_accepts_valid_data(self, valid_form_data):
        """Form should accept valid data."""
        form = RegistrationForm(data=valid_form_data)
        assert form.is_valid()

    @pytest.mark.parametrize(
        "missing_field",
        ["school_name", "contact_email", "phone"],
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
            "contact_email": "contact@example.com",
            "phone": "555-1234",
        }
        form = RegistrationForm(data=form_data)
        assert form.is_valid()
        registration = form.save()
        assert registration.pk is not None
        assert registration.status == "pending"
