"""Test role-based access denial using Django test client (no browser needed)."""

import pytest
from django.test import Client

from .conftest import _create_role_user, make_test_data, resolve_url
from .page_registry import get_denied_test_cases

pytestmark = [pytest.mark.django_db]

_denied_cases = get_denied_test_cases()
_denied_ids = [f"{p.url_name}--{r}" for p, r in _denied_cases]


@pytest.mark.parametrize("page_def,role", _denied_cases, ids=_denied_ids)
def test_denied_roles_cannot_access(page_def, role):
    """Denied roles should get a redirect, 403, or access-denied message."""
    test_data = make_test_data()
    user = _create_role_user(role, None)

    client = Client()
    if user is not None:
        client.force_login(user)

    requested_path = resolve_url(page_def, test_data)
    response = client.get(requested_path, follow=True)

    if role == "unauthenticated":
        # Should redirect to login
        final_url = response.redirect_chain[-1][0] if response.redirect_chain else ""
        assert "/auth/login/" in final_url, (
            f"{page_def.url_name} as unauthenticated: expected login redirect, got {final_url}"
        )
    else:
        content = response.content.decode().lower()
        final_path = response.request["PATH_INFO"] if not response.redirect_chain else response.redirect_chain[-1][0]
        is_denied = (
            response.status_code == 403
            or "access denied" in content
            or "you do not have permission" in content
            or "/auth/login/" in str(final_path)
            or (response.redirect_chain and final_path != requested_path)
        )
        assert is_denied, f"{page_def.url_name} as {role}: expected denial, got status={response.status_code}"
