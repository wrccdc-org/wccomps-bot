"""Tests for context processors."""

import pytest
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth.models import User
from django.test import RequestFactory

from core.context_processors import permissions

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

    def test_white_team_user_has_is_white_team_true(self, request_factory, social_app):
        """User in WCComps_WhiteTeam group should have is_white_team = True."""
        user = User.objects.create_user(username="whiteteam", password="test")

        _social_account = SocialAccount.objects.create(
            user=user,
            provider="authentik",
            uid="white-team-uid",
            extra_data={
                "userinfo": {
                    "groups": ["WCComps_WhiteTeam"],
                    "preferred_username": "whiteteam",
                },
            },
        )

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_white_team"] is True
        assert context["is_orange_team"] is False
        assert context["is_gold_team"] is False
        assert context["is_blue_team"] is False
        assert context["is_red_team"] is False

    def test_orange_team_user_has_is_orange_team_true(self, request_factory, social_app):
        """User in WCComps_OrangeTeam group should have is_orange_team = True."""
        user = User.objects.create_user(username="orangeteam", password="test")

        _social_account = SocialAccount.objects.create(
            user=user,
            provider="authentik",
            uid="orange-team-uid",
            extra_data={
                "userinfo": {
                    "groups": ["WCComps_OrangeTeam"],
                    "preferred_username": "orangeteam",
                },
            },
        )

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_orange_team"] is True
        assert context["is_white_team"] is False
        assert context["is_gold_team"] is False
        assert context["is_blue_team"] is False
        assert context["is_red_team"] is False

    def test_user_with_multiple_teams(self, request_factory, social_app):
        """User in both WhiteTeam and OrangeTeam should have both flags True."""
        user = User.objects.create_user(username="multipleams", password="test")

        _social_account = SocialAccount.objects.create(
            user=user,
            provider="authentik",
            uid="multiple-teams-uid",
            extra_data={
                "userinfo": {
                    "groups": ["WCComps_WhiteTeam", "WCComps_OrangeTeam"],
                    "preferred_username": "multipleams",
                },
            },
        )

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_white_team"] is True
        assert context["is_orange_team"] is True

    def test_non_white_team_user_has_is_white_team_false(self, request_factory, social_app):
        """User not in WCComps_WhiteTeam group should have is_white_team = False."""
        user = User.objects.create_user(username="goldteam", password="test")

        _social_account = SocialAccount.objects.create(
            user=user,
            provider="authentik",
            uid="gold-team-uid",
            extra_data={
                "userinfo": {
                    "groups": ["WCComps_GoldTeam"],
                    "preferred_username": "goldteam",
                },
            },
        )

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_white_team"] is False
        assert context["is_orange_team"] is False
        assert context["is_gold_team"] is True

    def test_non_orange_team_user_has_is_orange_team_false(self, request_factory, social_app):
        """User not in WCComps_OrangeTeam group should have is_orange_team = False."""
        user = User.objects.create_user(username="admin", password="test")

        _social_account = SocialAccount.objects.create(
            user=user,
            provider="authentik",
            uid="admin-uid",
            extra_data={
                "userinfo": {
                    "groups": ["WCComps_Discord_Admin"],
                    "preferred_username": "admin",
                },
            },
        )

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_orange_team"] is False
        assert context["is_white_team"] is False
        assert context["is_admin"] is True

    def test_user_without_social_account_returns_false(self, request_factory):
        """User without SocialAccount should have all team flags False."""
        user = User.objects.create_user(username="nosocial", password="test")

        request = request_factory.get("/")
        request.user = user

        context = permissions(request)

        assert context["is_white_team"] is False
        assert context["is_orange_team"] is False
        assert context["is_gold_team"] is False
        assert context["is_blue_team"] is False
        assert context["is_red_team"] is False
