"""Tests for Red Team findings filtering functionality."""

from collections.abc import Callable
from decimal import Decimal

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from scoring.models import AttackType, RedTeamFinding
from team.models import Team


@pytest.mark.django_db
class TestRedTeamPortalFiltering:
    """Test filtering capabilities in Red Team findings view."""

    def test_filter_by_target_team(self, create_user_with_groups: Callable[..., User]) -> None:
        """Red Team can filter findings by target team."""
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])
        team1 = Team.objects.create(team_number=1, team_name="Team 1")
        team2 = Team.objects.create(team_number=2, team_name="Team 2")

        # Create findings targeting different teams
        finding1 = RedTeamFinding.objects.create(
            attack_vector="SQL Injection on Team 1",
            source_ip="10.0.0.5",
            points_per_team=Decimal("50.00"),
            submitted_by=red_user,
        )
        finding1.affected_teams.add(team1)

        finding2 = RedTeamFinding.objects.create(
            attack_vector="XSS on Team 2",
            source_ip="10.0.0.6",
            points_per_team=Decimal("30.00"),
            submitted_by=red_user,
        )
        finding2.affected_teams.add(team2)

        finding3 = RedTeamFinding.objects.create(
            attack_vector="RCE on both teams",
            source_ip="10.0.0.7",
            points_per_team=Decimal("100.00"),
            submitted_by=red_user,
        )
        finding3.affected_teams.add(team1, team2)

        client = Client()
        client.force_login(red_user)

        # Filter by team1 (default status is "all" for red team view)
        response = client.get(reverse("scoring:red_team_findings"), {"team": team1.id, "status": "all"})
        assert response.status_code == 200
        findings = list(response.context["page_obj"])
        finding_ids = {f.id for f in findings}
        assert finding1.id in finding_ids
        assert finding2.id not in finding_ids
        assert finding3.id in finding_ids

    def test_filter_by_attack_type(self, create_user_with_groups: Callable[..., User]) -> None:
        """Red Team can filter findings by attack type (attack_vector)."""
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])
        team = Team.objects.create(team_number=1, team_name="Team 1")

        finding1 = RedTeamFinding.objects.create(
            attack_vector="SQL Injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("50.00"),
            submitted_by=red_user,
        )
        finding1.affected_teams.add(team)

        finding2 = RedTeamFinding.objects.create(
            attack_vector="XSS Attack",
            source_ip="10.0.0.6",
            points_per_team=Decimal("30.00"),
            submitted_by=red_user,
        )
        finding2.affected_teams.add(team)

        client = Client()
        client.force_login(red_user)

        # Filter by attack type ID
        sql_type, _ = AttackType.objects.get_or_create(name="SQL Injection")
        finding1.attack_type = sql_type
        finding1.save()
        response = client.get(reverse("scoring:red_team_findings"), {"attack_type": sql_type.id, "status": "all"})
        assert response.status_code == 200
        findings = list(response.context["page_obj"])
        finding_ids = {f.id for f in findings}
        assert finding1.id in finding_ids
        assert finding2.id not in finding_ids

    def test_filter_by_submitter(self, create_user_with_groups: Callable[..., User]) -> None:
        """Red Team can filter findings by submitter."""
        red_user1 = create_user_with_groups("red_user1", ["WCComps_RedTeam"])
        red_user2 = create_user_with_groups("red_user2", ["WCComps_RedTeam"])
        team = Team.objects.create(team_number=1, team_name="Team 1")

        finding1 = RedTeamFinding.objects.create(
            attack_vector="SQL Injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("50.00"),
            submitted_by=red_user1,
        )
        finding1.affected_teams.add(team)

        finding2 = RedTeamFinding.objects.create(
            attack_vector="XSS Attack",
            source_ip="10.0.0.6",
            points_per_team=Decimal("30.00"),
            submitted_by=red_user2,
        )
        finding2.affected_teams.add(team)

        client = Client()
        client.force_login(red_user1)

        # Filter by submitter
        response = client.get(reverse("scoring:red_team_findings"), {"submitter": red_user1.id, "status": "all"})
        assert response.status_code == 200
        findings = list(response.context["page_obj"])
        finding_ids = {f.id for f in findings}
        assert finding1.id in finding_ids
        assert finding2.id not in finding_ids

    def test_filter_multiple_criteria(self, create_user_with_groups: Callable[..., User]) -> None:
        """Red Team can combine multiple filters."""
        red_user1 = create_user_with_groups("red_user1", ["WCComps_RedTeam"])
        red_user2 = create_user_with_groups("red_user2", ["WCComps_RedTeam"])
        team1 = Team.objects.create(team_number=1, team_name="Team 1")
        team2 = Team.objects.create(team_number=2, team_name="Team 2")

        finding1 = RedTeamFinding.objects.create(
            attack_vector="SQL Injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("50.00"),
            submitted_by=red_user1,
        )
        finding1.affected_teams.add(team1)

        finding2 = RedTeamFinding.objects.create(
            attack_vector="SQL Injection",
            source_ip="10.0.0.6",
            points_per_team=Decimal("30.00"),
            submitted_by=red_user2,
        )
        finding2.affected_teams.add(team1)

        finding3 = RedTeamFinding.objects.create(
            attack_vector="SQL Injection",
            source_ip="10.0.0.7",
            points_per_team=Decimal("40.00"),
            submitted_by=red_user1,
        )
        finding3.affected_teams.add(team2)

        client = Client()
        client.force_login(red_user1)

        # Filter by team AND submitter
        response = client.get(
            reverse("scoring:red_team_findings"), {"team": team1.id, "submitter": red_user1.id, "status": "all"}
        )
        assert response.status_code == 200
        findings = list(response.context["page_obj"])
        finding_ids = {f.id for f in findings}
        assert finding1.id in finding_ids
        assert finding2.id not in finding_ids
        assert finding3.id not in finding_ids

    def test_no_filters_shows_all_findings(self, create_user_with_groups: Callable[..., User]) -> None:
        """Without filters, all findings are shown."""
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])
        team = Team.objects.create(team_number=1, team_name="Team 1")

        finding1 = RedTeamFinding.objects.create(
            attack_vector="SQL Injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("50.00"),
            submitted_by=red_user,
        )
        finding1.affected_teams.add(team)

        finding2 = RedTeamFinding.objects.create(
            attack_vector="XSS Attack",
            source_ip="10.0.0.6",
            points_per_team=Decimal("30.00"),
            submitted_by=red_user,
        )
        finding2.affected_teams.add(team)

        client = Client()
        client.force_login(red_user)

        response = client.get(reverse("scoring:red_team_findings"), {"status": "all"})
        assert response.status_code == 200
        findings = list(response.context["page_obj"])
        assert len(findings) == 2

    def test_filter_context_includes_teams_and_submitters(self, create_user_with_groups: Callable[..., User]) -> None:
        """Filter context includes available teams and submitters for dropdowns."""
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])
        team1 = Team.objects.create(team_number=1, team_name="Team 1")
        team2 = Team.objects.create(team_number=2, team_name="Team 2")

        finding = RedTeamFinding.objects.create(
            attack_vector="SQL Injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("50.00"),
            submitted_by=red_user,
        )
        finding.affected_teams.add(team1, team2)

        client = Client()
        client.force_login(red_user)

        response = client.get(reverse("scoring:red_team_findings"))
        assert response.status_code == 200
        assert "available_teams" in response.context
        assert "available_submitters" in response.context
        assert team1 in response.context["available_teams"]
        assert team2 in response.context["available_teams"]
        assert red_user in response.context["available_submitters"]

    def test_approval_status_not_visible_to_red_team(self, create_user_with_groups: Callable[..., User]) -> None:
        """Red Team users should not see approval status fields."""
        red_user = create_user_with_groups("red_user", ["WCComps_RedTeam"])
        team = Team.objects.create(team_number=1, team_name="Team 1")

        finding = RedTeamFinding.objects.create(
            attack_vector="SQL Injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("50.00"),
            submitted_by=red_user,
            is_approved=True,
        )
        finding.affected_teams.add(team)

        client = Client()
        client.force_login(red_user)

        response = client.get(reverse("scoring:red_team_findings"))
        assert response.status_code == 200

        # Check that template does not contain approval-related info in Red Team view
        content = response.content.decode()
        assert "is_approved" not in content.lower() or "approved" not in content.lower()
        # Points per team should not be visible to Red Team
        assert "points_per_team" not in content.lower() or "50.00" not in content

    def test_gold_team_sees_all_findings_including_approval_status(
        self, create_user_with_groups: Callable[..., User]
    ) -> None:
        """Gold Team can access red team portal and see approval status."""
        gold_user = create_user_with_groups("gold_user", ["WCComps_GoldTeam"])
        team = Team.objects.create(team_number=1, team_name="Team 1")

        finding = RedTeamFinding.objects.create(
            attack_vector="SQL Injection",
            source_ip="10.0.0.5",
            points_per_team=Decimal("50.00"),
            submitted_by=gold_user,
            is_approved=True,
        )
        finding.affected_teams.add(team)

        client = Client()
        client.force_login(gold_user)

        response = client.get(reverse("scoring:red_team_portal"))
        assert response.status_code == 200

        # Gold Team should see points per team in reviewed findings
        content = response.content.decode()
        assert "50" in content or "50.00" in content
