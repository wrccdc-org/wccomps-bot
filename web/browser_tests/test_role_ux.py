"""Test role-based access control and role-specific UI elements."""

import pytest
from django.urls import reverse

from .conftest import _create_role_user, create_session_context, visit_and_capture_errors
from .page_registry import get_denied_test_cases, get_element_check_cases
from .test_console_errors import _make_test_data, _resolve_url

pytestmark = [pytest.mark.browser, pytest.mark.django_db(transaction=True)]


# -- Access denial tests --

_denied_cases = get_denied_test_cases()
_denied_ids = [f"{p.url_name}--{r}" for p, r in _denied_cases]


@pytest.mark.parametrize("page_def,role", _denied_cases, ids=_denied_ids)
def test_denied_roles_cannot_access(page_def, role, live_server, pw_browser):
    """Denied roles should get a redirect, 403, or access-denied message."""
    test_data = _make_test_data()
    user = _create_role_user(role, None)
    context = create_session_context(pw_browser, live_server, user)

    try:
        url = live_server.url + _resolve_url(page_def, test_data)
        page, status_code, _errors = visit_and_capture_errors(context, url)

        if role == "unauthenticated":
            # Should redirect to login
            assert "/auth/login/" in page.url, (
                f"{page_def.url_name} as unauthenticated: expected login redirect, got {page.url}"
            )
        else:
            # Either 403, or 200 with access denied message
            content = page.content().lower()
            is_denied = (
                status_code == 403
                or "access denied" in content
                or "you do not have permission" in content
                or "/auth/login/" in page.url
            )
            assert is_denied, (
                f"{page_def.url_name} as {role}: expected denial, got status={status_code} url={page.url}"
            )
        page.close()
    finally:
        context.close()


# -- Element presence/absence tests --

_element_cases = get_element_check_cases()
_element_ids = [f"{p.url_name}--{r}" for p, r in _element_cases]


@pytest.mark.parametrize("page_def,role", _element_cases, ids=_element_ids)
def test_role_specific_elements(page_def, role, live_server, pw_browser):
    """Verify role-specific UI elements are present or absent."""
    test_data = _make_test_data()
    user = _create_role_user(role, None)
    context = create_session_context(pw_browser, live_server, user)

    try:
        url = live_server.url + _resolve_url(page_def, test_data)
        page, status_code, _errors = visit_and_capture_errors(context, url)

        assert status_code == 200, (
            f"{page_def.url_name} as {role}: expected 200, got {status_code}"
        )

        checks = page_def.checks[role]

        for selector in checks.get("present", []):
            count = page.locator(selector).count()
            assert count > 0, (
                f"{page_def.url_name} as {role}: expected '{selector}' to be present, found 0"
            )

        for selector in checks.get("absent", []):
            count = page.locator(selector).count()
            assert count == 0, (
                f"{page_def.url_name} as {role}: expected '{selector}' to be absent, found {count}"
            )

        page.close()
    finally:
        context.close()
