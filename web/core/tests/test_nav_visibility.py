"""Test that primary nav and scoring sub-nav visibility matches role permissions.

These tests replicate the {% if %} conditions from templates and verify them
against the context processor output for each role. If a template condition
changes, update the corresponding NAV_CONDITIONS / SCORING_SUBNAV_CONDITIONS
dict here.

Source templates:
  - templates/admin/base_site.html  (primary nav)
  - templates/scoring/base.html     (scoring sub-nav)
"""

import pytest
from django.contrib.auth.models import User
from django.test import RequestFactory

from core.context_processors import permissions
from core.models import UserGroups

pytestmark = pytest.mark.django_db

# Role name → Authentik group(s)
ROLE_GROUPS: dict[str, list[str]] = {
    "blue_team": ["WCComps_BlueTeam01"],
    "red_team": ["WCComps_RedTeam"],
    "gold_team": ["WCComps_GoldTeam"],
    "orange_team": ["WCComps_OrangeTeam"],
    "white_team": ["WCComps_WhiteTeam"],
    "ticketing_support": ["WCComps_Ticketing_Support"],
    "ticketing_admin": ["WCComps_Ticketing_Admin"],
    "admin": ["WCComps_Discord_Admin"],
}

# ---------------------------------------------------------------------------
# Primary nav conditions — must match templates/admin/base_site.html
# ---------------------------------------------------------------------------
NAV_CONDITIONS: dict[str, callable] = {
    "Tickets": lambda c: c["is_ticketing_support"] or c["is_ticketing_admin"],
    "Incident Report": lambda c: c["is_blue_team"] or c["is_white_team"] or c["is_gold_team"] or c["is_admin"],
    "Red Team Findings": lambda c: c["is_red_team"] or c["is_admin"],
    "Orange Team": lambda c: c["is_orange_team"] or c["is_admin"],
    "Leaderboard": (
        lambda c: (
            c["is_gold_team"] or c["is_white_team"] or c["is_red_team"] or c["is_ticketing_admin"] or c["is_admin"]
        )
    ),
    "Scoring Review": lambda c: c["is_gold_team"] or c["is_white_team"] or c["is_admin"],
    "White Team": lambda c: c["is_white_team"] or c["is_gold_team"] or c["is_admin"],
    "Competition": lambda c: c["is_gold_team"] or c["is_admin"],
    "Django Admin": lambda c: c["is_admin"],
}


# ---------------------------------------------------------------------------
# Scoring sub-nav conditions — must match templates/scoring/base.html
# The outer wrapper requires: is_gold_team or is_white_team or is_admin
# ---------------------------------------------------------------------------
def _scoring_wrapper(c: dict) -> bool:
    return c["is_gold_team"] or c["is_white_team"] or c["is_admin"]


SCORING_SUBNAV_CONDITIONS: dict[str, callable] = {
    "Red Team Scores": lambda c: _scoring_wrapper(c) and (c["is_gold_team"] or c["is_admin"]),
    "Orange Checks": lambda c: _scoring_wrapper(c) and (c["is_gold_team"] or c["is_admin"]),
    "Incidents": _scoring_wrapper,
    "Inject Grades": _scoring_wrapper,
    "Ticket Points": (
        lambda c: _scoring_wrapper(c) and (c["is_ticketing_admin"] or c["is_gold_team"] or c["is_admin"])
    ),
}

# ---------------------------------------------------------------------------
# Expected nav links per role — derived from the conditions above.
# If a test fails, either the template changed or permissions changed.
# ---------------------------------------------------------------------------
EXPECTED_PRIMARY_NAV: dict[str, set[str]] = {
    "blue_team": {"Incident Report"},
    "red_team": {"Red Team Findings", "Leaderboard"},
    "gold_team": {"Incident Report", "Orange Team", "Leaderboard", "Scoring Review", "White Team", "Competition"},
    "orange_team": {"Orange Team"},
    "white_team": {"Incident Report", "Leaderboard", "Scoring Review", "White Team"},
    "ticketing_support": {"Tickets"},
    "ticketing_admin": {"Tickets", "Leaderboard"},
    "admin": set(NAV_CONDITIONS.keys()),
}

EXPECTED_SCORING_SUBNAV: dict[str, set[str]] = {
    "blue_team": set(),
    "red_team": set(),
    "gold_team": {"Red Team Scores", "Orange Checks", "Incidents", "Inject Grades", "Ticket Points"},
    "orange_team": set(),
    "white_team": {"Incidents", "Inject Grades"},
    "ticketing_support": set(),
    "ticketing_admin": set(),
    "admin": set(SCORING_SUBNAV_CONDITIONS.keys()),
}


def _make_context(role: str) -> dict:
    """Create a user with the given role and return the permissions context."""
    user = User.objects.create_user(username=f"navtest_{role}", password="test")
    UserGroups.objects.create(
        user=user,
        authentik_id=f"navtest-{role}-uid",
        groups=ROLE_GROUPS[role],
    )
    request = RequestFactory().get("/")
    request.user = user
    # Attach a minimal resolver_match so _get_nav_active doesn't fail
    request.resolver_match = None
    return permissions(request)


def _visible_links(conditions: dict, context: dict) -> set[str]:
    """Evaluate nav conditions against a context and return visible link names."""
    return {name for name, cond in conditions.items() if cond(context)}


class TestPrimaryNavVisibility:
    """Verify each role sees exactly the correct primary nav links."""

    @pytest.mark.parametrize("role", ROLE_GROUPS.keys())
    def test_primary_nav_matches_expected(self, role):
        ctx = _make_context(role)
        visible = _visible_links(NAV_CONDITIONS, ctx)
        expected = EXPECTED_PRIMARY_NAV[role]
        assert visible == expected, (
            f"{role}: expected nav {sorted(expected)}, got {sorted(visible)}\n"
            f"  Extra: {sorted(visible - expected)}\n"
            f"  Missing: {sorted(expected - visible)}"
        )

    @pytest.mark.parametrize("role", ROLE_GROUPS.keys())
    def test_conditions_match_expected(self, role):
        """Cross-check: NAV_CONDITIONS evaluated against context must match EXPECTED_PRIMARY_NAV.

        This catches cases where EXPECTED_PRIMARY_NAV was updated but the
        template conditions (NAV_CONDITIONS) were not, or vice versa.
        """
        ctx = _make_context(role)
        visible = _visible_links(NAV_CONDITIONS, ctx)
        expected = EXPECTED_PRIMARY_NAV[role]
        assert visible == expected


class TestScoringSubnavVisibility:
    """Verify each role sees exactly the correct scoring sub-nav links."""

    @pytest.mark.parametrize("role", ROLE_GROUPS.keys())
    def test_scoring_subnav_matches_expected(self, role):
        ctx = _make_context(role)
        visible = _visible_links(SCORING_SUBNAV_CONDITIONS, ctx)
        expected = EXPECTED_SCORING_SUBNAV[role]
        assert visible == expected, (
            f"{role}: expected scoring subnav {sorted(expected)}, got {sorted(visible)}\n"
            f"  Extra: {sorted(visible - expected)}\n"
            f"  Missing: {sorted(expected - visible)}"
        )
