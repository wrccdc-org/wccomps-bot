"""Tests for OrangeTeamBonus approval tracking fields."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from scoring.models import OrangeTeamBonus
from team.models import Team


class OrangeTeamBonusApprovalTests(TestCase):
    """Test OrangeTeamBonus approval tracking fields."""

    def setUp(self) -> None:
        """Set up test data."""
        self.user = User.objects.create_user(username="testuser", password="test123")
        self.approver = User.objects.create_user(username="approver", password="test123")
        self.team = Team.objects.create(team_number=1, team_name="Test Team 1")

    def test_new_bonus_has_is_approved_false_by_default(self) -> None:
        """New bonuses should have is_approved=False by default."""
        bonus = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Test bonus",
            points_awarded=Decimal("50.00"),
            submitted_by=self.user,
        )

        self.assertFalse(bonus.is_approved)

    def test_new_bonus_has_approved_at_null(self) -> None:
        """New bonuses should have approved_at=None."""
        bonus = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Test bonus",
            points_awarded=Decimal("50.00"),
            submitted_by=self.user,
        )

        self.assertIsNone(bonus.approved_at)

    def test_new_bonus_has_approved_by_null(self) -> None:
        """New bonuses should have approved_by=None."""
        bonus = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Test bonus",
            points_awarded=Decimal("50.00"),
            submitted_by=self.user,
        )

        self.assertIsNone(bonus.approved_by)

    def test_can_set_is_approved_to_true(self) -> None:
        """Should be able to set is_approved to True."""
        bonus = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Test bonus",
            points_awarded=Decimal("50.00"),
            submitted_by=self.user,
        )

        bonus.is_approved = True
        bonus.save()
        bonus.refresh_from_db()

        self.assertTrue(bonus.is_approved)

    def test_can_set_approved_at_timestamp(self) -> None:
        """Should be able to set approved_at timestamp."""
        bonus = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Test bonus",
            points_awarded=Decimal("50.00"),
            submitted_by=self.user,
        )

        approval_time = timezone.now()
        bonus.approved_at = approval_time
        bonus.save()
        bonus.refresh_from_db()

        self.assertEqual(bonus.approved_at, approval_time)

    def test_can_set_approved_by_user(self) -> None:
        """Should be able to set approved_by to a User."""
        bonus = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Test bonus",
            points_awarded=Decimal("50.00"),
            submitted_by=self.user,
        )

        bonus.approved_by = self.approver
        bonus.save()
        bonus.refresh_from_db()

        self.assertEqual(bonus.approved_by, self.approver)

    def test_approved_by_allows_null(self) -> None:
        """approved_by field should allow null values."""
        bonus = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Test bonus",
            points_awarded=Decimal("50.00"),
            submitted_by=self.user,
            approved_by=self.approver,
        )

        bonus.approved_by = None
        bonus.save()
        bonus.refresh_from_db()

        self.assertIsNone(bonus.approved_by)

    def test_approved_at_allows_null(self) -> None:
        """approved_at field should allow null values."""
        bonus = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Test bonus",
            points_awarded=Decimal("50.00"),
            submitted_by=self.user,
            approved_at=timezone.now(),
        )

        bonus.approved_at = None
        bonus.save()
        bonus.refresh_from_db()

        self.assertIsNone(bonus.approved_at)

    def test_can_query_by_is_approved(self) -> None:
        """Should be able to filter bonuses by is_approved field."""
        approved_bonus = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Approved bonus",
            points_awarded=Decimal("50.00"),
            submitted_by=self.user,
            is_approved=True,
        )
        unapproved_bonus = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Unapproved bonus",
            points_awarded=Decimal("30.00"),
            submitted_by=self.user,
            is_approved=False,
        )

        approved_bonuses = OrangeTeamBonus.objects.filter(is_approved=True)
        unapproved_bonuses = OrangeTeamBonus.objects.filter(is_approved=False)

        self.assertIn(approved_bonus, approved_bonuses)
        self.assertNotIn(unapproved_bonus, approved_bonuses)
        self.assertIn(unapproved_bonus, unapproved_bonuses)
        self.assertNotIn(approved_bonus, unapproved_bonuses)

    def test_approved_by_set_null_when_user_deleted(self) -> None:
        """approved_by should be set to NULL when the approver user is deleted."""
        bonus = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Test bonus",
            points_awarded=Decimal("50.00"),
            submitted_by=self.user,
            approved_by=self.approver,
        )

        self.approver.delete()
        bonus.refresh_from_db()

        self.assertIsNone(bonus.approved_by)

    def test_full_approval_workflow(self) -> None:
        """Test complete approval workflow."""
        bonus = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Test bonus",
            points_awarded=Decimal("50.00"),
            submitted_by=self.user,
        )

        self.assertFalse(bonus.is_approved)
        self.assertIsNone(bonus.approved_at)
        self.assertIsNone(bonus.approved_by)

        approval_time = timezone.now()
        bonus.is_approved = True
        bonus.approved_at = approval_time
        bonus.approved_by = self.approver
        bonus.save()
        bonus.refresh_from_db()

        self.assertTrue(bonus.is_approved)
        self.assertEqual(bonus.approved_at, approval_time)
        self.assertEqual(bonus.approved_by, self.approver)
