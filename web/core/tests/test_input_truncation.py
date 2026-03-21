"""Tests that all user-facing form inputs are truncated to their model's max_length.

Prevents DataError (StringDataRightTruncation) when users submit oversized input.
Each parametrized case posts a form with an oversized field and verifies no 500.

To add coverage for a new field, add a single entry to TRUNCATION_CASES.
"""

import pytest
from django.test import Client
from django.urls import reverse

pytestmark = pytest.mark.django_db

OVERSIZED = "x" * 1000  # Well beyond any max_length in the codebase


# (test_id, url_name, overrides, client_fixture, extra_fixtures)
# "overrides" maps the field-under-test to OVERSIZED; remaining keys are valid defaults.
TRUNCATION_CASES = [
    # ── Ticket creation ───────────────────────────────────────────────
    (
        "ticket__ip_address",
        "create_ticket",
        {"title": "Test", "ip_address": OVERSIZED},
        "blue_client",
        ["default_category", "mock_quotient_client"],
    ),
    (
        "ticket__hostname",
        "create_ticket",
        {"title": "Test", "hostname": OVERSIZED},
        "blue_client",
        ["default_category", "mock_quotient_client"],
    ),
    (
        "ticket__service_name",
        "create_ticket",
        {"title": "Test", "service_name": OVERSIZED},
        "blue_client",
        ["default_category", "mock_quotient_client"],
    ),
    # ── Orange check creation ─────────────────────────────────────────
    (
        "orange_check__title",
        "challenges:check_create",
        {
            "title": OVERSIZED,
            "description": "desc",
            "criterion_label_0": "crit",
            "criterion_points_0": "10",
        },
        "orange_client",
        [],
    ),
    (
        "orange_check__criterion_label",
        "challenges:check_create",
        {
            "title": "Test Check",
            "description": "desc",
            "criterion_label_0": OVERSIZED,
            "criterion_points_0": "10",
        },
        "orange_client",
        [],
    ),
]


@pytest.fixture
def blue_client(blue_team_user):
    client = Client()
    client.force_login(blue_team_user)
    return client


@pytest.fixture
def orange_client(orange_team_user):
    client = Client()
    client.force_login(orange_team_user)
    return client


@pytest.mark.parametrize(
    "url_name, form_data, client_fixture, extras",
    [(c[1], c[2], c[3], c[4]) for c in TRUNCATION_CASES],
    ids=[c[0] for c in TRUNCATION_CASES],
)
def test_oversized_input_no_500(url_name, form_data, client_fixture, extras, request):
    """No CharField should cause a 500 when submitted with oversized input."""
    http_client = request.getfixturevalue(client_fixture)
    # Activate extra fixtures (e.g. mock_quotient_client, default_category)
    for fixture_name in extras:
        fixture_val = request.getfixturevalue(fixture_name)
        # Inject category PK into ticket form data if needed
        if fixture_name == "default_category":
            form_data = {**form_data, "category": fixture_val.pk}

    response = http_client.post(reverse(url_name), form_data)
    assert response.status_code != 500, f"POST {url_name} returned 500 with oversized field"
