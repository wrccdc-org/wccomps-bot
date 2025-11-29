"""Tests for registration models."""

import pytest
from django.contrib.auth.models import User

from ..models import TeamRegistration


@pytest.fixture
def admin_user(db):
    """Create admin user for tests."""
    return User.objects.create_user(username="admin", password="admin123")


@pytest.mark.django_db
class TestTeamRegistration:
    """Test TeamRegistration model."""

    def test_registration_creation(self):
        """Test registration can be created with required fields."""
        registration = TeamRegistration.objects.create(
            school_name="Test High School",
            contact_email="test@example.com",
            phone="555-1234",
        )
        assert registration.school_name == "Test High School"
        assert registration.contact_email == "test@example.com"
        assert registration.phone == "555-1234"
        assert registration.status == "pending"
        assert registration.submitted_at is not None

    def test_registration_defaults(self):
        """Test registration default values."""
        registration = TeamRegistration.objects.create(
            school_name="Test School", contact_email="test@example.com", phone="555-0000"
        )
        assert registration.status == "pending"
        assert registration.approved_at is None
        assert registration.paid_at is None
        assert registration.credentials_sent_at is None
        assert registration.rejection_reason == ""
        assert registration.approved_by is None

    def test_status_choices(self):
        """Test valid status choices."""
        valid_statuses = ["pending", "approved", "paid", "credentials_sent", "rejected"]
        for status in valid_statuses:
            registration = TeamRegistration.objects.create(
                school_name=f"School {status}",
                contact_email=f"{status}@example.com",
                phone="555-0000",
                status=status,
            )
            assert registration.status == status

    def test_approve_registration(self, admin_user):
        """Test approving a registration."""
        registration = TeamRegistration.objects.create(
            school_name="Test School", contact_email="test@example.com", phone="555-0000"
        )
        registration.approve(admin_user)
        assert registration.status == "approved"
        assert registration.approved_at is not None
        assert registration.approved_by == admin_user

    def test_reject_registration(self):
        """Test rejecting a registration."""
        registration = TeamRegistration.objects.create(
            school_name="Test School", contact_email="test@example.com", phone="555-0000"
        )
        reason = "Incomplete information"
        registration.reject(reason)
        assert registration.status == "rejected"
        assert registration.rejection_reason == reason

    def test_mark_as_paid(self):
        """Test marking registration as paid."""
        registration = TeamRegistration.objects.create(
            school_name="Test School", contact_email="test@example.com", phone="555-0000", status="approved"
        )
        registration.mark_as_paid()
        assert registration.status == "paid"
        assert registration.paid_at is not None

    def test_mark_credentials_sent(self):
        """Test marking credentials as sent."""
        registration = TeamRegistration.objects.create(
            school_name="Test School", contact_email="test@example.com", phone="555-0000", status="paid"
        )
        registration.mark_credentials_sent()
        assert registration.status == "credentials_sent"
        assert registration.credentials_sent_at is not None

    def test_string_representation(self):
        """Test string representation."""
        registration = TeamRegistration.objects.create(
            school_name="Test School", contact_email="test@example.com", phone="555-0000"
        )
        expected = "Test School (pending)"
        assert str(registration) == expected

    def test_email_validation(self):
        """Test email field validation."""
        registration = TeamRegistration.objects.create(
            school_name="Test School", contact_email="valid@example.com", phone="555-0000"
        )
        assert registration.contact_email == "valid@example.com"

    def test_ordering(self):
        """Test registrations are ordered by submission date (newest first)."""
        reg1 = TeamRegistration.objects.create(
            school_name="School 1", contact_email="test1@example.com", phone="555-0001"
        )
        reg2 = TeamRegistration.objects.create(
            school_name="School 2", contact_email="test2@example.com", phone="555-0002"
        )
        reg3 = TeamRegistration.objects.create(
            school_name="School 3", contact_email="test3@example.com", phone="555-0003"
        )

        registrations = list(TeamRegistration.objects.all())
        assert registrations[0] == reg3
        assert registrations[1] == reg2
        assert registrations[2] == reg1
