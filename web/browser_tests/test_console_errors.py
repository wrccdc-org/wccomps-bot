"""Test that all pages render without JS or CSP console errors for each role."""

import pytest
from django.urls import reverse

from .conftest import _create_role_user, create_session_context, visit_and_capture_errors
from .page_registry import PageDef, get_allowed_test_cases

pytestmark = [pytest.mark.browser, pytest.mark.django_db(transaction=True)]


def _make_test_data():
    """Create shared test data needed by pages with needs_data."""
    from team.models import Team
    from ticketing.models import Ticket

    team, _ = Team.objects.get_or_create(
        team_number=1,
        defaults={
            "team_name": "Test Team 01",
            "authentik_group": "WCComps_BlueTeam01",
            "is_active": True,
        },
    )

    ticket = Ticket.objects.create(
        title="Browser Test Ticket",
        description="Created for browser tests",
        team=team,
        status="open",
    )

    return {
        "ticket": ticket,
        "team": team,
    }


def _resolve_url(page_def: PageDef, test_data: dict) -> str:
    """Build the URL path for a PageDef, filling dynamic kwargs from test_data."""
    kwargs = dict(page_def.url_kwargs)
    if page_def.needs_data == "ticket":
        kwargs["ticket_number"] = test_data["ticket"].ticket_number
    elif page_def.needs_data == "team":
        kwargs["team_number"] = test_data["team"].team_number
    return reverse(page_def.url_name, kwargs=kwargs)


# Generate test IDs like "ticket_list--blue_team"
_allowed_cases = get_allowed_test_cases()
_allowed_ids = [f"{p.url_name}--{r}" for p, r in _allowed_cases]


@pytest.mark.parametrize("page_def,role", _allowed_cases, ids=_allowed_ids)
def test_no_console_errors(page_def, role, live_server, pw_browser):
    """Every allowed page x role combination should render with zero console errors."""
    test_data = _make_test_data()
    user = _create_role_user(role, None)
    context = create_session_context(pw_browser, live_server, user)

    try:
        url = live_server.url + _resolve_url(page_def, test_data)
        page, status_code, errors = visit_and_capture_errors(context, url)

        if page_def.expect_redirect:
            # Redirecting pages — just check no errors during redirect
            assert not errors, (
                f"Console errors on {page_def.url_name} as {role}:\n" + "\n".join(errors)
            )
        else:
            assert status_code == 200, (
                f"{page_def.url_name} as {role}: expected 200, got {status_code}"
            )
            assert not errors, (
                f"Console errors on {page_def.url_name} as {role}:\n" + "\n".join(errors)
            )
        page.close()
    finally:
        context.close()
