"""
Tests for Orange Team adjustment approval workflow (FEAT-4).

Following TDD methodology - tests written first to define expected behavior.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from team.models import Team

from .models import OrangeTeamBonus


class IndividualOrangeApprovalTests(TestCase):
    """Test individual approval/rejection of Orange adjustments."""

    def setUp(self) -> None:
        """Set up test data."""
        # Create users (Person objects are auto-created via post_save signal)
        self.orange_user = User.objects.create_user(username="orange", password="test123")
        self.gold_user = User.objects.create_user(username="gold", password="test123")
        self.blue_user = User.objects.create_user(username="blue", password="test123")

        # Update Person objects with roles
        self.orange_person = self.orange_user.person
        self.orange_person.discord_id = 111111
        self.orange_person.authentik_groups = ["WCComps_OrangeTeam"]
        self.orange_person.save()

        self.gold_person = self.gold_user.person
        self.gold_person.discord_id = 222222
        self.gold_person.authentik_groups = ["WCComps_GoldTeam"]
        self.gold_person.save()

        self.blue_person = self.blue_user.person
        self.blue_person.discord_id = 333333
        self.blue_person.authentik_groups = ["WCComps_BlueTeam01"]
        self.blue_person.save()

        # Create team
        self.team = Team.objects.create(team_number=1, team_name="Team 1")

        # Create unapproved adjustment
        self.adjustment = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Good customer service",
            points_awarded=Decimal("50.00"),
            submitted_by=self.orange_user,
        )

        self.client = Client()

    def test_gold_team_can_approve_individual_adjustment(self) -> None:
        """Gold Team member can approve an individual adjustment."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:approve_orange_adjustment", args=[self.adjustment.id])

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)  # Redirect after success
        self.adjustment.refresh_from_db()
        self.assertTrue(self.adjustment.is_approved)
        self.assertIsNotNone(self.adjustment.approved_at)
        self.assertEqual(self.adjustment.approved_by, self.gold_user)

    def test_gold_team_can_reject_individual_adjustment(self) -> None:
        """Gold Team member can reject an individual adjustment."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:reject_orange_adjustment", args=[self.adjustment.id])

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)  # Redirect after success
        self.adjustment.refresh_from_db()
        self.assertFalse(self.adjustment.is_approved)
        self.assertIsNone(self.adjustment.approved_at)
        self.assertIsNone(self.adjustment.approved_by)

    def test_approve_sets_timestamp(self) -> None:
        """Approving an adjustment sets the approved_at timestamp."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:approve_orange_adjustment", args=[self.adjustment.id])

        before_approval = timezone.now()
        response = self.client.post(url)
        after_approval = timezone.now()

        self.assertEqual(response.status_code, 302)
        self.adjustment.refresh_from_db()
        self.assertIsNotNone(self.adjustment.approved_at)
        assert self.adjustment.approved_at is not None  # Type narrowing for mypy
        self.assertGreaterEqual(self.adjustment.approved_at, before_approval)
        self.assertLessEqual(self.adjustment.approved_at, after_approval)

    def test_non_gold_team_cannot_approve(self) -> None:
        """Non-Gold Team members cannot approve adjustments."""
        self.client.login(username="orange", password="test123")
        url = reverse("scoring:approve_orange_adjustment", args=[self.adjustment.id])

        response = self.client.post(url)

        # Should redirect or forbidden
        self.assertIn(response.status_code, [302, 403])
        self.adjustment.refresh_from_db()
        self.assertFalse(self.adjustment.is_approved)

    def test_non_gold_team_cannot_reject(self) -> None:
        """Non-Gold Team members cannot reject adjustments."""
        self.client.login(username="blue", password="test123")
        url = reverse("scoring:reject_orange_adjustment", args=[self.adjustment.id])

        response = self.client.post(url)

        # Should redirect or forbidden
        self.assertIn(response.status_code, [302, 403])
        self.adjustment.refresh_from_db()
        self.assertFalse(self.adjustment.is_approved)

    def test_unauthenticated_cannot_approve(self) -> None:
        """Unauthenticated users cannot approve adjustments."""
        url = reverse("scoring:approve_orange_adjustment", args=[self.adjustment.id])
        response = self.client.post(url)

        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        assert response.url is not None  # Type narrowing for mypy
        self.assertIn("login", response.url.lower())
        self.adjustment.refresh_from_db()
        self.assertFalse(self.adjustment.is_approved)

    def test_approve_nonexistent_adjustment_returns_404(self) -> None:
        """Approving non-existent adjustment returns 404."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:approve_orange_adjustment", args=[99999])

        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_reject_nonexistent_adjustment_returns_404(self) -> None:
        """Rejecting non-existent adjustment returns 404."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:reject_orange_adjustment", args=[99999])

        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_approve_only_accepts_post(self) -> None:
        """Approve endpoint only accepts POST requests."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:approve_orange_adjustment", args=[self.adjustment.id])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)  # Method not allowed

    def test_reject_only_accepts_post(self) -> None:
        """Reject endpoint only accepts POST requests."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:reject_orange_adjustment", args=[self.adjustment.id])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)  # Method not allowed

    def test_can_approve_already_approved_adjustment(self) -> None:
        """Can re-approve an already approved adjustment (updates approver)."""
        # First approval
        self.adjustment.is_approved = True
        self.adjustment.approved_by = self.orange_user  # Different user
        self.adjustment.approved_at = timezone.now()
        self.adjustment.save()

        # Second approval by gold team
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:approve_orange_adjustment", args=[self.adjustment.id])

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        self.adjustment.refresh_from_db()
        self.assertTrue(self.adjustment.is_approved)
        self.assertEqual(self.adjustment.approved_by, self.gold_user)

    def test_admin_can_approve_adjustment(self) -> None:
        """Admin users can approve adjustments."""
        admin_user = User.objects.create_user(username="admin", password="test123", is_staff=True)
        self.client.login(username="admin", password="test123")
        url = reverse("scoring:approve_orange_adjustment", args=[self.adjustment.id])

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        self.adjustment.refresh_from_db()
        self.assertTrue(self.adjustment.is_approved)
        self.assertEqual(self.adjustment.approved_by, admin_user)


class BulkOrangeApprovalTests(TestCase):
    """Test bulk approval/rejection of Orange adjustments."""

    def setUp(self) -> None:
        """Set up test data."""
        # Create users (Person objects are auto-created via post_save signal)
        self.gold_user = User.objects.create_user(username="gold", password="test123")
        self.orange_user = User.objects.create_user(username="orange", password="test123")

        # Update Person objects with roles
        self.gold_person = self.gold_user.person
        self.gold_person.discord_id = 222222
        self.gold_person.authentik_groups = ["WCComps_GoldTeam"]
        self.gold_person.save()

        self.orange_person = self.orange_user.person
        self.orange_person.discord_id = 111111
        self.orange_person.authentik_groups = ["WCComps_OrangeTeam"]
        self.orange_person.save()

        # Create teams
        self.team1 = Team.objects.create(team_number=1, team_name="Team 1")
        self.team2 = Team.objects.create(team_number=2, team_name="Team 2")

        # Create multiple unapproved adjustments
        self.adj1 = OrangeTeamBonus.objects.create(
            team=self.team1,
            description="Adjustment 1",
            points_awarded=Decimal("50.00"),
            submitted_by=self.orange_user,
        )
        self.adj2 = OrangeTeamBonus.objects.create(
            team=self.team2,
            description="Adjustment 2",
            points_awarded=Decimal("30.00"),
            submitted_by=self.orange_user,
        )
        self.adj3 = OrangeTeamBonus.objects.create(
            team=self.team1,
            description="Adjustment 3",
            points_awarded=Decimal("-20.00"),
            submitted_by=self.orange_user,
        )

        self.client = Client()

    def test_bulk_approve_multiple_adjustments(self) -> None:
        """Can bulk approve multiple adjustments at once."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:bulk_approve_orange_adjustments")

        response = self.client.post(url, {"adjustment_ids": [self.adj1.id, self.adj2.id]})

        self.assertEqual(response.status_code, 302)
        self.adj1.refresh_from_db()
        self.adj2.refresh_from_db()
        self.adj3.refresh_from_db()

        self.assertTrue(self.adj1.is_approved)
        self.assertTrue(self.adj2.is_approved)
        self.assertFalse(self.adj3.is_approved)  # Not in selection

    def test_bulk_reject_multiple_adjustments(self) -> None:
        """Can bulk reject multiple adjustments at once."""
        # First approve all
        self.adj1.is_approved = True
        self.adj1.approved_by = self.gold_user
        self.adj1.approved_at = timezone.now()
        self.adj1.save()

        self.adj2.is_approved = True
        self.adj2.approved_by = self.gold_user
        self.adj2.approved_at = timezone.now()
        self.adj2.save()

        # Now bulk reject
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:bulk_reject_orange_adjustments")

        response = self.client.post(url, {"adjustment_ids": [self.adj1.id, self.adj2.id]})

        self.assertEqual(response.status_code, 302)
        self.adj1.refresh_from_db()
        self.adj2.refresh_from_db()

        self.assertFalse(self.adj1.is_approved)
        self.assertFalse(self.adj2.is_approved)
        self.assertIsNone(self.adj1.approved_by)
        self.assertIsNone(self.adj2.approved_by)

    def test_bulk_approve_sets_approver_for_all(self) -> None:
        """Bulk approve sets the approver user for all adjustments."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:bulk_approve_orange_adjustments")

        response = self.client.post(url, {"adjustment_ids": [self.adj1.id, self.adj2.id]})

        self.assertEqual(response.status_code, 302)
        self.adj1.refresh_from_db()
        self.adj2.refresh_from_db()

        self.assertEqual(self.adj1.approved_by, self.gold_user)
        self.assertEqual(self.adj2.approved_by, self.gold_user)

    def test_bulk_approve_empty_selection(self) -> None:
        """Bulk approve with empty selection returns gracefully."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:bulk_approve_orange_adjustments")

        response = self.client.post(url, {"adjustment_ids": []})

        # Should redirect back without error
        self.assertEqual(response.status_code, 302)

    def test_bulk_approve_invalid_ids_skipped(self) -> None:
        """Bulk approve skips invalid adjustment IDs."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:bulk_approve_orange_adjustments")

        response = self.client.post(url, {"adjustment_ids": [self.adj1.id, 99999]})

        self.assertEqual(response.status_code, 302)
        self.adj1.refresh_from_db()
        self.assertTrue(self.adj1.is_approved)

    def test_non_gold_team_cannot_bulk_approve(self) -> None:
        """Non-Gold Team members cannot bulk approve."""
        self.client.login(username="orange", password="test123")
        url = reverse("scoring:bulk_approve_orange_adjustments")

        response = self.client.post(url, {"adjustment_ids": [self.adj1.id, self.adj2.id]})

        self.assertIn(response.status_code, [302, 403])
        self.adj1.refresh_from_db()
        self.adj2.refresh_from_db()
        self.assertFalse(self.adj1.is_approved)
        self.assertFalse(self.adj2.is_approved)

    def test_bulk_approve_only_accepts_post(self) -> None:
        """Bulk approve endpoint only accepts POST requests."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:bulk_approve_orange_adjustments")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_bulk_reject_only_accepts_post(self) -> None:
        """Bulk reject endpoint only accepts POST requests."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:bulk_reject_orange_adjustments")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)


class OrangePortalApprovalUITests(TestCase):
    """Test that approval UI is shown/hidden based on user role."""

    def setUp(self) -> None:
        """Set up test data."""
        # Create users (Person objects are auto-created via post_save signal)
        self.gold_user = User.objects.create_user(username="gold", password="test123")
        self.orange_user = User.objects.create_user(username="orange", password="test123")
        self.admin_user = User.objects.create_user(username="admin", password="test123", is_staff=True)

        # Update Person objects with roles
        self.gold_person = self.gold_user.person
        self.gold_person.discord_id = 222222
        self.gold_person.authentik_groups = ["WCComps_GoldTeam"]
        self.gold_person.save()

        self.orange_person = self.orange_user.person
        self.orange_person.discord_id = 111111
        self.orange_person.authentik_groups = ["WCComps_OrangeTeam"]
        self.orange_person.save()

        # Create team and adjustments
        self.team = Team.objects.create(team_number=1, team_name="Team 1")
        self.adjustment = OrangeTeamBonus.objects.create(
            team=self.team,
            description="Test adjustment",
            points_awarded=Decimal("50.00"),
            submitted_by=self.orange_user,
        )

        self.client = Client()

    def test_gold_team_sees_approval_controls(self) -> None:
        """Gold Team members see approval controls in orange portal."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:orange_team_portal")

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Approve")
        self.assertContains(response, "Reject")
        # Check for bulk action buttons
        self.assertContains(response, "Approve Selected")

    def test_orange_team_does_not_see_approval_controls(self) -> None:
        """Orange Team members do NOT see approval controls."""
        self.client.login(username="orange", password="test123")
        url = reverse("scoring:orange_team_portal")

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Approve")
        self.assertNotContains(response, "Reject")
        self.assertNotContains(response, "Approve Selected")

    def test_admin_sees_approval_controls(self) -> None:
        """Admin users see approval controls."""
        self.client.login(username="admin", password="test123")
        url = reverse("scoring:orange_team_portal")

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Approve")
        self.assertContains(response, "Reject")

    def test_gold_team_sees_all_adjustments(self) -> None:
        """Gold Team sees all adjustments, not just their own."""
        # Create another adjustment by different user
        other_user = User.objects.create_user(username="other", password="test123")
        OrangeTeamBonus.objects.create(
            team=self.team,
            description="Other adjustment",
            points_awarded=Decimal("30.00"),
            submitted_by=other_user,
        )

        self.client.login(username="gold", password="test123")
        url = reverse("scoring:orange_team_portal")

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        # Should see both adjustments
        self.assertEqual(len(response.context["bonuses"]), 2)

    def test_orange_team_sees_only_their_adjustments(self) -> None:
        """Orange Team members only see their own adjustments."""
        # Create another adjustment by different user
        other_user = User.objects.create_user(username="other", password="test123")
        OrangeTeamBonus.objects.create(
            team=self.team,
            description="Other adjustment",
            points_awarded=Decimal("30.00"),
            submitted_by=other_user,
        )

        self.client.login(username="orange", password="test123")
        url = reverse("scoring:orange_team_portal")

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        # Should only see their own adjustment
        self.assertEqual(len(response.context["bonuses"]), 1)
        self.assertEqual(response.context["bonuses"][0].submitted_by, self.orange_user)

    def test_approval_status_displayed(self) -> None:
        """Approval status is displayed in the portal."""
        # Create approved adjustment
        OrangeTeamBonus.objects.create(
            team=self.team,
            description="Approved adjustment",
            points_awarded=Decimal("40.00"),
            submitted_by=self.orange_user,
            is_approved=True,
            approved_by=self.gold_user,
            approved_at=timezone.now(),
        )

        self.client.login(username="gold", password="test123")
        url = reverse("scoring:orange_team_portal")

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        # Should indicate approval status
        content = response.content.decode()
        self.assertIn("Approved", content)

    def test_gold_team_sees_checkbox_column(self) -> None:
        """Gold Team sees checkbox column for bulk selection."""
        self.client.login(username="gold", password="test123")
        url = reverse("scoring:orange_team_portal")

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'type="checkbox"')

    def test_orange_team_does_not_see_checkbox_column(self) -> None:
        """Orange Team does not see checkbox column."""
        self.client.login(username="orange", password="test123")
        url = reverse("scoring:orange_team_portal")

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        # Should not have checkboxes for selection
        content = response.content.decode()
        # If there are checkboxes, they shouldn't be for bulk selection
        if 'type="checkbox"' in content:
            self.assertNotContains(response, 'name="adjustment_ids"')
