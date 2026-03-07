"""Test that all pages render without JS or CSP console errors for each role."""

import pytest

from .conftest import (
    _create_role_user,
    create_session_context,
    make_test_data,
    resolve_url,
    visit_and_capture_errors,
)
from .page_registry import get_allowed_test_cases

pytestmark = [pytest.mark.browser, pytest.mark.django_db(transaction=True)]

# Generate test IDs like "ticket_list--blue_team"
_allowed_cases = get_allowed_test_cases()
_allowed_ids = [f"{p.url_name}--{r}" for p, r in _allowed_cases]


@pytest.mark.parametrize("page_def,role", _allowed_cases, ids=_allowed_ids)
def test_no_console_errors(page_def, role, live_server, pw_browser):
    """Every allowed page x role combination should render with zero console errors."""
    test_data = make_test_data()
    user = _create_role_user(role, None)
    context = create_session_context(pw_browser, live_server, user)

    try:
        url = live_server.url + resolve_url(page_def, test_data)
        page, status_code, errors = visit_and_capture_errors(context, url)

        if page_def.expect_redirect:
            # Redirecting pages — just check no errors during redirect
            assert not errors, f"Console errors on {page_def.url_name} as {role}:\n" + "\n".join(errors)
        else:
            assert status_code == 200, f"{page_def.url_name} as {role}: expected 200, got {status_code}"
            assert not errors, f"Console errors on {page_def.url_name} as {role}:\n" + "\n".join(errors)
    finally:
        context.close()
