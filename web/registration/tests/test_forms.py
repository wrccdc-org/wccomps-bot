"""Tests for registration forms."""

from django.test import TestCase

from ..forms import RegistrationForm


class RegistrationFormTestCase(TestCase):
    """Test RegistrationForm."""

    def test_form_valid_data(self):
        """Test form with valid data."""
        form_data = {
            "school_name": "Test High School",
            "contact_email": "contact@example.com",
            "phone": "555-1234",
        }
        form = RegistrationForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_form_missing_school_name(self):
        """Test form with missing school name."""
        form_data = {
            "contact_email": "contact@example.com",
            "phone": "555-1234",
        }
        form = RegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("school_name", form.errors)

    def test_form_missing_email(self):
        """Test form with missing email."""
        form_data = {
            "school_name": "Test School",
            "phone": "555-1234",
        }
        form = RegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("contact_email", form.errors)

    def test_form_missing_phone(self):
        """Test form with missing phone."""
        form_data = {
            "school_name": "Test School",
            "contact_email": "contact@example.com",
        }
        form = RegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("phone", form.errors)

    def test_form_invalid_email(self):
        """Test form with invalid email format."""
        form_data = {
            "school_name": "Test School",
            "contact_email": "not-an-email",
            "phone": "555-1234",
        }
        form = RegistrationForm(data=form_data)
        self.assertFalse(form.is_valid())
        self.assertIn("contact_email", form.errors)

    def test_form_fields_rendered(self):
        """Test form has expected fields."""
        form = RegistrationForm()
        self.assertIn("school_name", form.fields)
        self.assertIn("contact_email", form.fields)
        self.assertIn("phone", form.fields)

    def test_form_field_labels(self):
        """Test form field labels are set correctly."""
        form = RegistrationForm()
        self.assertEqual(form.fields["school_name"].label, "School Name")
        self.assertEqual(form.fields["contact_email"].label, "Contact Email")
        self.assertEqual(form.fields["phone"].label, "Phone Number")

    def test_form_saves_correctly(self):
        """Test form saves model correctly."""
        form_data = {
            "school_name": "Test High School",
            "contact_email": "contact@example.com",
            "phone": "555-1234",
        }
        form = RegistrationForm(data=form_data)
        self.assertTrue(form.is_valid())
        registration = form.save()
        self.assertEqual(registration.school_name, "Test High School")
        self.assertEqual(registration.contact_email, "contact@example.com")
        self.assertEqual(registration.phone, "555-1234")
        self.assertEqual(registration.status, "pending")
