"""Tests for email scorecard views."""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from core.models import UserGroups
from scoring.models import FinalScore, ScoringTemplate
from team.models import SchoolInfo, Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def gold_user():
    user = User.objects.create_user(username="gold", password="testpass123")
    UserGroups.objects.create(user=user, authentik_id="gold-uid", groups=["WCComps_GoldTeam"])
    return user


@pytest.fixture
def red_user():
    user = User.objects.create_user(username="red", password="testpass123")
    UserGroups.objects.create(user=user, authentik_id="red-uid", groups=["WCComps_RedTeam"])
    return user


@pytest.fixture
def teams():
    return [
        Team.objects.create(team_number=1, team_name="Team 01", is_active=True),
        Team.objects.create(team_number=2, team_name="Team 02", is_active=True),
    ]


@pytest.fixture
def school_infos(teams):
    return [
        SchoolInfo.objects.create(
            team=teams[0],
            school_name="Alpha High",
            contact_email="alpha@example.edu",
            secondary_email="alpha2@example.edu",
        ),
        SchoolInfo.objects.create(
            team=teams[1],
            school_name="Beta Academy",
            contact_email="beta@example.edu",
        ),
    ]


@pytest.fixture
def scoring_template():
    return ScoringTemplate.objects.create(
        service_weight=Decimal("40"),
        inject_weight=Decimal("40"),
        orange_weight=Decimal("20"),
        service_max=Decimal("1000"),
        inject_max=Decimal("500"),
        orange_max=Decimal("100"),
    )


@pytest.fixture
def final_scores(teams, scoring_template):
    return [
        FinalScore.objects.create(
            team=teams[0],
            service_points=Decimal("500"),
            inject_points=Decimal("300"),
            orange_points=Decimal("100"),
            red_deductions=Decimal("-50"),
            sla_penalties=Decimal("-10"),
            total_score=Decimal("840"),
            rank=1,
        ),
        FinalScore.objects.create(
            team=teams[1],
            service_points=Decimal("400"),
            inject_points=Decimal("250"),
            orange_points=Decimal("80"),
            red_deductions=Decimal("-30"),
            sla_penalties=Decimal("-5"),
            total_score=Decimal("695"),
            rank=2,
        ),
    ]


class TestEmailScorecardsPermissions:
    """Test that only gold team can access email scorecard views."""

    def test_non_gold_user_cannot_access_bulk_email(self, red_user, final_scores):
        client = Client()
        client.force_login(red_user)
        response = client.get(reverse("scoring:email_scorecards"))
        assert response.status_code == 302

    def test_non_gold_user_cannot_access_single_email(self, red_user, final_scores):
        client = Client()
        client.force_login(red_user)
        response = client.get(reverse("scoring:email_scorecard", args=[1]))
        assert response.status_code == 302

    def test_gold_user_can_access_bulk_email(self, gold_user, final_scores, school_infos):
        client = Client()
        client.force_login(gold_user)
        response = client.get(reverse("scoring:email_scorecards"))
        assert response.status_code == 200

    def test_gold_user_can_access_single_email(self, gold_user, final_scores, school_infos):
        client = Client()
        client.force_login(gold_user)
        response = client.get(reverse("scoring:email_scorecard", args=[1]))
        assert response.status_code == 200


class TestBulkEmailScorecardsGET:
    """Test the bulk email confirmation page."""

    def test_shows_teams_with_emails(self, gold_user, final_scores, school_infos):
        client = Client()
        client.force_login(gold_user)
        response = client.get(reverse("scoring:email_scorecards"))
        content = response.content.decode()
        assert "alpha@example.edu" in content
        assert "beta@example.edu" in content

    def test_shows_teams_without_school_info(self, gold_user, teams, final_scores):
        """Teams without SchoolInfo should show 'No email'."""
        client = Client()
        client.force_login(gold_user)
        response = client.get(reverse("scoring:email_scorecards"))
        content = response.content.decode()
        assert "No email" in content

    def test_redirects_when_no_scores(self, gold_user, teams):
        client = Client()
        client.force_login(gold_user)
        response = client.get(reverse("scoring:email_scorecards"))
        assert response.status_code == 302


class TestBulkEmailScorecardsPost:
    """Test the bulk email POST action."""

    @patch("core.email.send_templated_email", return_value=True)
    def test_sends_emails_to_all_teams_with_school_info(self, mock_send, gold_user, final_scores, school_infos):
        client = Client()
        client.force_login(gold_user)
        response = client.post(reverse("scoring:email_scorecards"))
        assert response.status_code == 302
        assert mock_send.call_count == 2

    @patch("core.email.send_templated_email", return_value=True)
    def test_skips_teams_without_school_info(self, mock_send, gold_user, teams, final_scores):
        """Teams without SchoolInfo should be skipped, not crash."""
        # No school_infos fixture — neither team has email
        client = Client()
        client.force_login(gold_user)
        response = client.post(reverse("scoring:email_scorecards"))
        assert response.status_code == 302
        assert mock_send.call_count == 0

    @patch("core.email.send_templated_email", return_value=True)
    def test_email_includes_pdf_attachment(self, mock_send, gold_user, final_scores, school_infos):
        client = Client()
        client.force_login(gold_user)
        client.post(reverse("scoring:email_scorecards"))

        call_kwargs = mock_send.call_args_list[0][1]
        attachments = call_kwargs["attachments"]
        assert len(attachments) == 1
        filename, content, mime = attachments[0]
        assert filename == "team-01-scorecard.pdf"
        assert mime == "application/pdf"
        assert isinstance(content, bytes)
        assert len(content) > 0

    @patch("core.email.send_templated_email", return_value=True)
    def test_email_sent_to_both_contact_emails(self, mock_send, gold_user, final_scores, school_infos):
        client = Client()
        client.force_login(gold_user)
        client.post(reverse("scoring:email_scorecards"))

        # Team 1 has both primary and secondary email
        call_kwargs = mock_send.call_args_list[0][1]
        assert call_kwargs["to"] == ["alpha@example.edu", "alpha2@example.edu"]

        # Team 2 has only primary
        call_kwargs = mock_send.call_args_list[1][1]
        assert call_kwargs["to"] == ["beta@example.edu"]

    @patch("core.email.send_templated_email", return_value=False)
    def test_reports_failed_emails(self, mock_send, gold_user, final_scores, school_infos):
        client = Client()
        client.force_login(gold_user)
        response = client.post(reverse("scoring:email_scorecards"), follow=True)
        content = response.content.decode()
        assert "Failed" in content


class TestSingleEmailScorecardGET:
    """Test the single team email confirmation page."""

    def test_shows_team_and_email_info(self, gold_user, final_scores, school_infos):
        client = Client()
        client.force_login(gold_user)
        response = client.get(reverse("scoring:email_scorecard", args=[1]))
        content = response.content.decode()
        assert "alpha@example.edu" in content
        assert "Alpha High" in content

    def test_redirects_when_no_school_info(self, gold_user, teams, final_scores):
        client = Client()
        client.force_login(gold_user)
        response = client.get(reverse("scoring:email_scorecard", args=[1]))
        assert response.status_code == 302


class TestSingleEmailScorecardPOST:
    """Test the single team email POST action."""

    @patch("core.email.send_templated_email", return_value=True)
    def test_sends_email_with_pdf(self, mock_send, gold_user, final_scores, school_infos):
        client = Client()
        client.force_login(gold_user)
        response = client.post(reverse("scoring:email_scorecard", args=[1]))
        assert response.status_code == 302
        assert mock_send.call_count == 1

        call_kwargs = mock_send.call_args[1]
        assert call_kwargs["to"] == ["alpha@example.edu", "alpha2@example.edu"]
        assert call_kwargs["template_name"] == "scorecard"
        assert len(call_kwargs["attachments"]) == 1

    @patch("core.email.send_templated_email", return_value=False)
    def test_reports_failure(self, mock_send, gold_user, final_scores, school_infos):
        client = Client()
        client.force_login(gold_user)
        response = client.post(reverse("scoring:email_scorecard", args=[1]), follow=True)
        content = response.content.decode()
        assert "Failed" in content
