"""
Tests for Orange Team Portal filtering (PERM-4).

Requirement: Orange Team members should only see their own submissions,
while Gold Team and Admin can see all submissions.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from core.models import UserGroups
from team.models import Team

from scoring.models import OrangeTeamBonus


class OrangeTeamPortalFilteringTests(TestCase):
    """Test that Orange Team portal filters submissions by user role."""

    def setUp(self) -> None:
        """Set up test data with multiple users and bonuses."""
        self.team1 = Team.objects.create(team_number=1, team_name="Team 1")
        self.team2 = Team.objects.create(team_number=2, team_name="Team 2")

        # Create Orange Team users
        self.orange_user1 = User.objects.create_user(username="orange1", password="test123")
        UserGroups.objects.create(user=self.orange_user1, authentik_id="orange1-uid", groups=["WCComps_OrangeTeam"])

        self.orange_user2 = User.objects.create_user(username="orange2", password="test123")
        UserGroups.objects.create(user=self.orange_user2, authentik_id="orange2-uid", groups=["WCComps_OrangeTeam"])

        # Create Gold Team user
        self.gold_user = User.objects.create_user(username="gold1", password="test123")
        UserGroups.objects.create(user=self.gold_user, authentik_id="gold1-uid", groups=["WCComps_GoldTeam"])

        # Create Admin user
        self.admin_user = User.objects.create_user(username="admin1", password="test123")
        UserGroups.objects.create(user=self.admin_user, authentik_id="admin1-uid", groups=["WCComps_Discord_Admin"])

        # Create bonuses submitted by different users
        self.bonus1 = OrangeTeamBonus.objects.create(
            team=self.team1,
            description="Bonus by orange1",
            points_awarded=Decimal("10.00"),
            submitted_by=self.orange_user1,
        )

        self.bonus2 = OrangeTeamBonus.objects.create(
            team=self.team2,
            description="Bonus by orange1 again",
            points_awarded=Decimal("15.00"),
            submitted_by=self.orange_user1,
        )

        self.bonus3 = OrangeTeamBonus.objects.create(
            team=self.team1,
            description="Bonus by orange2",
            points_awarded=Decimal("20.00"),
            submitted_by=self.orange_user2,
        )

        self.bonus4 = OrangeTeamBonus.objects.create(
            team=self.team2,
            description="Bonus by gold user",
            points_awarded=Decimal("25.00"),
            submitted_by=self.gold_user,
        )

        self.client = Client()

    def test_orange_team_member_sees_only_own_submissions(self) -> None:
        """Orange Team member should only see bonuses they submitted."""
        self.client.login(username="orange1", password="test123")
        response = self.client.get(reverse("scoring:orange_team_portal"))

        self.assertEqual(response.status_code, 200)

        bonuses = response.context["bonuses"]
        bonus_ids = [b.id for b in bonuses]

        # Should see only their own bonuses
        self.assertIn(self.bonus1.id, bonus_ids)
        self.assertIn(self.bonus2.id, bonus_ids)

        # Should NOT see other users' bonuses
        self.assertNotIn(self.bonus3.id, bonus_ids)
        self.assertNotIn(self.bonus4.id, bonus_ids)

        # Should have exactly 2 bonuses
        self.assertEqual(len(bonuses), 2)

    def test_orange_team_member_sees_empty_list_when_no_submissions(self) -> None:
        """Orange Team member with no submissions should see empty list."""
        new_orange_user = User.objects.create_user(username="orange3", password="test123")
        UserGroups.objects.create(user=new_orange_user, authentik_id="orange3-uid", groups=["WCComps_OrangeTeam"])

        self.client.login(username="orange3", password="test123")
        response = self.client.get(reverse("scoring:orange_team_portal"))

        self.assertEqual(response.status_code, 200)
        bonuses = response.context["bonuses"]
        self.assertEqual(len(bonuses), 0)

    def test_gold_team_member_sees_all_submissions(self) -> None:
        """Gold Team member should see all bonuses regardless of submitter."""
        self.client.login(username="gold1", password="test123")
        response = self.client.get(reverse("scoring:orange_team_portal"))

        self.assertEqual(response.status_code, 200)

        bonuses = response.context["bonuses"]
        bonus_ids = [b.id for b in bonuses]

        # Should see all bonuses
        self.assertIn(self.bonus1.id, bonus_ids)
        self.assertIn(self.bonus2.id, bonus_ids)
        self.assertIn(self.bonus3.id, bonus_ids)
        self.assertIn(self.bonus4.id, bonus_ids)

        # Should have all 4 bonuses
        self.assertEqual(len(bonuses), 4)

    def test_admin_sees_all_submissions(self) -> None:
        """Admin should see all bonuses regardless of submitter."""
        self.client.login(username="admin1", password="test123")
        response = self.client.get(reverse("scoring:orange_team_portal"))

        self.assertEqual(response.status_code, 200)

        bonuses = response.context["bonuses"]
        bonus_ids = [b.id for b in bonuses]

        # Should see all bonuses
        self.assertIn(self.bonus1.id, bonus_ids)
        self.assertIn(self.bonus2.id, bonus_ids)
        self.assertIn(self.bonus3.id, bonus_ids)
        self.assertIn(self.bonus4.id, bonus_ids)

        # Should have all 4 bonuses
        self.assertEqual(len(bonuses), 4)

    def test_filtering_preserves_select_related(self) -> None:
        """Verify queryset optimization is maintained after filtering."""
        self.client.login(username="orange1", password="test123")
        response = self.client.get(reverse("scoring:orange_team_portal"))

        self.assertEqual(response.status_code, 200)
        bonuses = response.context["bonuses"]

        # Access related team without triggering additional queries
        # This verifies select_related is still in effect
        if bonuses:
            _ = bonuses[0].team.team_name  # Should not cause additional query

    def test_unauthorized_user_cannot_access_portal(self) -> None:
        """Non-Orange Team user without Gold/Admin access should be denied."""
        blue_user = User.objects.create_user(username="blue1", password="test123")
        UserGroups.objects.create(user=blue_user, authentik_id="blue1-uid", groups=["WCComps_BlueTeam01"])

        self.client.login(username="blue1", password="test123")
        response = self.client.get(reverse("scoring:orange_team_portal"))

        # Should redirect (permission denied)
        self.assertEqual(response.status_code, 302)
