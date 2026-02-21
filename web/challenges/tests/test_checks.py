import pytest
from django.contrib.auth.models import User
from django.test import Client

from challenges.models import OrangeCheck
from core.models import UserGroups

pytestmark = pytest.mark.django_db


class TestCheckList:
    def test_lead_can_access(self) -> None:
        user = User.objects.create_user(username="gold1", password="test")
        UserGroups.objects.create(user=user, authentik_id="g1", groups=["WCComps_GoldTeam"])
        client = Client()
        client.login(username="gold1", password="test")
        response = client.get("/orange-team/checks/")
        assert response.status_code == 200

    def test_non_lead_denied(self) -> None:
        user = User.objects.create_user(username="orange1", password="test")
        UserGroups.objects.create(user=user, authentik_id="o1", groups=["WCComps_OrangeTeam"])
        client = Client()
        client.login(username="orange1", password="test")
        response = client.get("/orange-team/checks/")
        assert response.status_code == 302

    def test_shows_checks_in_list(self) -> None:
        user = User.objects.create_user(username="gold2", password="test")
        UserGroups.objects.create(user=user, authentik_id="g2", groups=["WCComps_GoldTeam"])
        OrangeCheck.objects.create(title="Test Check", description="desc", created_by=user)
        client = Client()
        client.login(username="gold2", password="test")
        response = client.get("/orange-team/checks/")
        assert response.status_code == 200
        assert b"Test Check" in response.content

    def test_empty_state_when_no_checks(self) -> None:
        user = User.objects.create_user(username="gold3", password="test")
        UserGroups.objects.create(user=user, authentik_id="g3", groups=["WCComps_GoldTeam"])
        client = Client()
        client.login(username="gold3", password="test")
        response = client.get("/orange-team/checks/")
        assert response.status_code == 200
        assert b"No checks" in response.content


class TestCheckCreate:
    def test_create_check_with_criteria(self) -> None:
        user = User.objects.create_user(username="gold1", password="test")
        UserGroups.objects.create(user=user, authentik_id="g1", groups=["WCComps_GoldTeam"])
        client = Client()
        client.login(username="gold1", password="test")
        response = client.post(
            "/orange-team/checks/create/",
            {
                "title": "Password Reset",
                "description": "Ask team to reset admin password",
                "criterion_label_0": "Fast response",
                "criterion_points_0": "3",
                "criterion_label_1": "Professional",
                "criterion_points_1": "3",
                "criterion_label_2": "Resolved",
                "criterion_points_2": "4",
            },
        )
        assert response.status_code == 302
        check = OrangeCheck.objects.get(title="Password Reset")
        assert check.criteria.count() == 3
        assert check.max_score == 10

    def test_create_requires_title(self) -> None:
        user = User.objects.create_user(username="gold1", password="test")
        UserGroups.objects.create(user=user, authentik_id="g1", groups=["WCComps_GoldTeam"])
        client = Client()
        client.login(username="gold1", password="test")
        response = client.post(
            "/orange-team/checks/create/",
            {
                "title": "",
                "description": "test",
                "criterion_label_0": "Fast",
                "criterion_points_0": "3",
            },
        )
        assert response.status_code == 200  # re-renders form with error

    def test_create_requires_criteria(self) -> None:
        user = User.objects.create_user(username="gold1", password="test")
        UserGroups.objects.create(user=user, authentik_id="g1", groups=["WCComps_GoldTeam"])
        client = Client()
        client.login(username="gold1", password="test")
        response = client.post(
            "/orange-team/checks/create/",
            {
                "title": "Test Check",
                "description": "test",
            },
        )
        assert response.status_code == 200  # re-renders form with error

    def test_get_shows_form(self) -> None:
        user = User.objects.create_user(username="gold1", password="test")
        UserGroups.objects.create(user=user, authentik_id="g1", groups=["WCComps_GoldTeam"])
        client = Client()
        client.login(username="gold1", password="test")
        response = client.get("/orange-team/checks/create/")
        assert response.status_code == 200
        assert b"Create Check" in response.content

    def test_non_lead_denied(self) -> None:
        user = User.objects.create_user(username="orange1", password="test")
        UserGroups.objects.create(user=user, authentik_id="o1", groups=["WCComps_OrangeTeam"])
        client = Client()
        client.login(username="orange1", password="test")
        response = client.post(
            "/orange-team/checks/create/",
            {
                "title": "Test",
                "criterion_label_0": "Fast",
                "criterion_points_0": "3",
            },
        )
        assert response.status_code == 302
