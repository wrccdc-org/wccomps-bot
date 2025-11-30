"""Tests for registration views."""

from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from ..models import TeamRegistration


class RegistrationViewTestCase(TestCase):
    """Test public registration view."""

    def setUp(self):
        """Set up test client."""
        self.client = Client()

    def test_registration_page_loads(self):
        """Test registration page loads without authentication."""
        response = self.client.get(reverse("registration_register"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/register.html")

    def test_registration_page_has_form(self):
        """Test registration page contains form."""
        response = self.client.get(reverse("registration_register"))
        self.assertContains(response, "school_name")
        self.assertContains(response, "contact_email")
        self.assertContains(response, "phone")

    def test_submit_valid_registration(self):
        """Test submitting valid registration."""
        form_data = {
            "school_name": "Test High School",
            "contact_email": "test@example.com",
            "phone": "555-1234",
        }
        response = self.client.post(reverse("registration_register"), data=form_data)
        self.assertEqual(response.status_code, 302)

        registration = TeamRegistration.objects.get(contact_email="test@example.com")
        self.assertEqual(registration.school_name, "Test High School")
        self.assertEqual(registration.status, "pending")

    def test_submit_invalid_registration(self):
        """Test submitting invalid registration shows errors."""
        form_data = {
            "school_name": "",
            "contact_email": "invalid-email",
            "phone": "",
        }
        response = self.client.post(reverse("registration_register"), data=form_data)
        self.assertEqual(response.status_code, 200)
        self.assertFormError(response.context["form"], "school_name", "This field is required.")


class AdminReviewListViewTestCase(TestCase):
    """Test admin review list view."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.admin_user = User.objects.create_user(username="admin", password="admin123")
        self.registration = TeamRegistration.objects.create(
            school_name="Test School", contact_email="test@example.com", phone="555-1234"
        )

    def test_review_list_requires_gold_team(self):
        """Test review list requires Gold Team permission."""
        response = self.client.get(reverse("registration_review_list"))
        self.assertEqual(response.status_code, 302)

    @patch("core.auth_utils.has_permission")
    def test_review_list_loads_for_gold_team(self, mock_has_permission):
        """Test review list loads for Gold Team users."""
        mock_has_permission.return_value = True
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("registration_review_list"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/review_list.html")

    @patch("core.auth_utils.has_permission")
    def test_review_list_shows_registrations(self, mock_has_permission):
        """Test review list displays all registrations."""
        mock_has_permission.return_value = True
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("registration_review_list"))
        self.assertContains(response, "Test School")
        self.assertContains(response, "test@example.com")

    @patch("core.auth_utils.has_permission")
    def test_review_list_filters_by_status(self, mock_has_permission):
        """Test review list can filter by status."""
        mock_has_permission.return_value = True
        TeamRegistration.objects.create(
            school_name="Approved School", contact_email="approved@example.com", phone="555-0000", status="approved"
        )
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("registration_review_list"), {"status": "pending"})
        self.assertContains(response, "Test School")
        self.assertNotContains(response, "Approved School")


class AdminApproveViewTestCase(TestCase):
    """Test admin approve action view."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.admin_user = User.objects.create_user(username="admin", password="admin123")
        self.registration = TeamRegistration.objects.create(
            school_name="Test School", contact_email="test@example.com", phone="555-1234"
        )

    def test_approve_requires_gold_team(self):
        """Test approve action requires Gold Team permission."""
        response = self.client.post(reverse("registration_approve", args=[self.registration.id]))
        self.assertEqual(response.status_code, 302)

    @patch("core.auth_utils.has_permission")
    def test_approve_registration(self, mock_has_permission):
        """Test approving a registration."""
        mock_has_permission.return_value = True
        self.client.force_login(self.admin_user)
        response = self.client.post(reverse("registration_approve", args=[self.registration.id]))
        self.assertEqual(response.status_code, 302)

        self.registration.refresh_from_db()
        self.assertEqual(self.registration.status, "approved")
        self.assertIsNotNone(self.registration.approved_at)
        self.assertEqual(self.registration.approved_by, self.admin_user)


class AdminRejectViewTestCase(TestCase):
    """Test admin reject action view."""

    def setUp(self):
        """Set up test data."""
        self.client = Client()
        self.admin_user = User.objects.create_user(username="admin", password="admin123")
        self.registration = TeamRegistration.objects.create(
            school_name="Test School", contact_email="test@example.com", phone="555-1234"
        )

    def test_reject_requires_gold_team(self):
        """Test reject action requires Gold Team permission."""
        response = self.client.post(reverse("registration_reject", args=[self.registration.id]))
        self.assertEqual(response.status_code, 302)

    @patch("core.auth_utils.has_permission")
    def test_reject_registration(self, mock_has_permission):
        """Test rejecting a registration."""
        mock_has_permission.return_value = True
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse("registration_reject", args=[self.registration.id]), {"reason": "Incomplete information"}
        )
        self.assertEqual(response.status_code, 302)

        self.registration.refresh_from_db()
        self.assertEqual(self.registration.status, "rejected")
        self.assertEqual(self.registration.rejection_reason, "Incomplete information")

    @patch("core.auth_utils.has_permission")
    def test_reject_requires_reason(self, mock_has_permission):
        """Test reject action requires a reason."""
        mock_has_permission.return_value = True
        self.client.force_login(self.admin_user)
        response = self.client.post(reverse("registration_reject", args=[self.registration.id]), {"reason": ""})
        self.assertEqual(response.status_code, 200)
