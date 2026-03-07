"""Central registry of pages to test, with role access and element expectations."""

from dataclasses import dataclass, field


@dataclass
class PageDef:
    url_name: str
    url_kwargs: dict[str, str | int] = field(default_factory=dict)
    needs_data: str | None = None  # "ticket", "team" — keys into test_data dict
    allowed_roles: list[str] = field(default_factory=list)
    denied_roles: list[str] = field(default_factory=list)
    expect_redirect: bool = False  # True if page redirects (e.g., home)
    checks: dict[str, dict[str, list[str]]] = field(default_factory=dict)
    # checks format: {"role": {"present": ["css selectors"], "absent": ["css selectors"]}}


# Pages to test. Add new entries here to expand coverage.
PAGES: list[PageDef] = [
    # -- Ticketing --
    PageDef(
        url_name="ticket_list",
        allowed_roles=["blue_team", "ticketing_support", "ticketing_admin", "admin"],
        denied_roles=["red_team", "gold_team", "orange_team", "unauthenticated"],
        checks={
            "blue_team": {"present": ["table"], "absent": [".bulk-claim-form"]},
            "admin": {"present": ["table"]},
        },
    ),
    PageDef(
        url_name="create_ticket",
        allowed_roles=["blue_team", "admin"],
        denied_roles=["red_team", "unauthenticated"],
        checks={
            "blue_team": {"present": ["form", "select[name='category']"]},
            "admin": {"present": ["form"]},
        },
    ),
    PageDef(
        url_name="ticket_detail",
        needs_data="ticket",
        allowed_roles=["blue_team", "ticketing_support", "admin"],
        denied_roles=["unauthenticated"],
    ),
    # -- Admin --
    PageDef(
        url_name="admin_competition",
        allowed_roles=["gold_team", "admin"],
        denied_roles=["blue_team", "red_team", "ticketing_support", "unauthenticated"],
    ),
    PageDef(
        url_name="admin_teams",
        allowed_roles=["gold_team", "admin"],
        denied_roles=["blue_team", "red_team", "unauthenticated"],
    ),
    PageDef(
        url_name="admin_team_detail",
        needs_data="team",
        allowed_roles=["gold_team", "admin"],
        denied_roles=["blue_team", "unauthenticated"],
    ),
    # -- Scoring --
    PageDef(
        url_name="scoring:leaderboard",
        allowed_roles=["blue_team", "admin"],
        denied_roles=["unauthenticated"],
    ),
    PageDef(
        url_name="scoring:submit_red_score",
        allowed_roles=["red_team", "admin"],
        denied_roles=["blue_team", "unauthenticated"],
    ),
    # scoring:submit_incident_report removed — depends on Quotient API
    PageDef(
        url_name="scoring:incident_list",
        allowed_roles=["blue_team", "admin"],
        denied_roles=["unauthenticated"],
    ),
    # -- Challenges (Orange Team) --
    PageDef(
        url_name="challenges:dashboard",
        allowed_roles=["orange_team", "gold_team", "admin"],
        denied_roles=["blue_team", "red_team", "unauthenticated"],
    ),
    # -- Packets --
    PageDef(
        url_name="team_packet",
        allowed_roles=["blue_team", "admin"],
        denied_roles=["red_team", "unauthenticated"],
    ),
    PageDef(
        url_name="packets_list",
        allowed_roles=["gold_team", "admin"],
        denied_roles=["blue_team", "red_team", "unauthenticated"],
    ),
    # -- Home (redirects based on role) --
    PageDef(
        url_name="home",
        expect_redirect=True,
        allowed_roles=["blue_team", "red_team", "gold_team", "admin"],
        denied_roles=[],
    ),
]


def get_allowed_test_cases() -> list[tuple[PageDef, str]]:
    """Generate (page_def, role) pairs for pages each role CAN access."""
    cases = []
    for page in PAGES:
        for role in page.allowed_roles:
            cases.append((page, role))
    return cases


def get_denied_test_cases() -> list[tuple[PageDef, str]]:
    """Generate (page_def, role) pairs for pages each role should be DENIED."""
    cases = []
    for page in PAGES:
        for role in page.denied_roles:
            cases.append((page, role))
    return cases


def get_element_check_cases() -> list[tuple[PageDef, str]]:
    """Generate (page_def, role) pairs that have element checks defined."""
    cases = []
    for page in PAGES:
        for role in page.checks:
            cases.append((page, role))
    return cases
