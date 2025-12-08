"""Tests for context processors."""

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory

from core.context_processors import permissions
from core.models import UserGroups

pytestmark = pytest.mark.django_db


@pytest.fixture
def request_factory():
    """Create a RequestFactory for generating mock requests."""
    return RequestFactory()


class TestPermissionsContextProcessor:
    """Test the permissions context processor."""

    def test_unauthenticated_user_returns_false_for_all_flags(self, request_factory):
        """Unauthenticated users should get False for all permission flags."""
        from django.contrib.auth.models import AnonymousUser

        request = request_factory.get("/")
        request.user = AnonymousUser()

        context = permissions(request)

        assert context["is_admin"] is False
        assert context["is_ticketing_admin"] is False
        assert context["is_ticketing_support"] is False
        assert context["is_gold_team"] is False
        assert context["is_blue_team"] is False
        assert context["is_red_team"] is False
        assert context["is_white_team"] is False
        assert context["is_orange_team"] is False
        assert context["authentik_username"] == ""

    def test_white_team_user_has_is_white_team_true(self, request_factory):
        """User in WCComps_WhiteTeam group should have is_white_team = True."""
        user = User.objects.create_user(username="whiteteam", password="test")
        UserGroups.objects.create(user=user, authentik_id="white-team-uid", groups=["WCComps_WhiteTeam"])

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_white_team"] is True
        assert context["is_orange_team"] is False
        assert context["is_gold_team"] is False
        assert context["is_blue_team"] is False
        assert context["is_red_team"] is False

    def test_orange_team_user_has_is_orange_team_true(self, request_factory):
        """User in WCComps_OrangeTeam group should have is_orange_team = True."""
        user = User.objects.create_user(username="orangeteam", password="test")
        UserGroups.objects.create(user=user, authentik_id="orange-team-uid", groups=["WCComps_OrangeTeam"])

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_orange_team"] is True
        assert context["is_white_team"] is False
        assert context["is_gold_team"] is False
        assert context["is_blue_team"] is False
        assert context["is_red_team"] is False

    def test_user_with_multiple_teams(self, request_factory):
        """User in both WhiteTeam and OrangeTeam should have both flags True."""
        user = User.objects.create_user(username="multipleams", password="test")
        UserGroups.objects.create(
            user=user, authentik_id="multiple-teams-uid", groups=["WCComps_WhiteTeam", "WCComps_OrangeTeam"]
        )

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_white_team"] is True
        assert context["is_orange_team"] is True

    def test_non_white_team_user_has_is_white_team_false(self, request_factory):
        """User not in WCComps_WhiteTeam group should have is_white_team = False."""
        user = User.objects.create_user(username="goldteam", password="test")
        UserGroups.objects.create(user=user, authentik_id="gold-team-uid", groups=["WCComps_GoldTeam"])

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_white_team"] is False
        assert context["is_orange_team"] is False
        assert context["is_gold_team"] is True

    def test_non_orange_team_user_has_is_orange_team_false(self, request_factory):
        """User not in WCComps_OrangeTeam group should have is_orange_team = False."""
        user = User.objects.create_user(username="admin", password="test")
        UserGroups.objects.create(user=user, authentik_id="admin-uid", groups=["WCComps_Discord_Admin"])

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_orange_team"] is False
        assert context["is_white_team"] is False
        assert context["is_admin"] is True

    def test_user_without_usergroups_returns_false(self, request_factory):
        """User without UserGroups should have all team flags False."""
        user = User.objects.create_user(username="nosocial", password="test")

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_white_team"] is False
        assert context["is_orange_team"] is False
        assert context["is_gold_team"] is False
        assert context["is_blue_team"] is False
        assert context["is_red_team"] is False
