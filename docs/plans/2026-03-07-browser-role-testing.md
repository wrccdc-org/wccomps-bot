# Browser-Based Role Testing Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Catch CSP violations, JS errors, and role-specific UX regressions by running Playwright browser tests against every page as every role, using force_login session injection (no OAuth).

**Architecture:** Playwright hits a pytest-django `live_server` on a random port. Test users are created with `create_user_with_groups`, force-logged-in via Django test Client, and the session cookie is injected into Playwright's browser context. Console errors and page errors are captured via event listeners and asserted to be empty.

**Tech Stack:** pytest, pytest-django (`live_server`), Playwright (sync API), existing `create_user_with_groups` fixture pattern

---

### Task 1: Add browser_tests to pytest config

**Files:**
- Modify: `pyproject.toml:145` (testpaths line)

**Step 1: Add `web/browser_tests` to testpaths**

In `pyproject.toml`, add `"web/browser_tests"` to the testpaths array:

```toml
testpaths = ["bot/tests", "web/core/tests", "web/scoring/tests", "web/team/tests", "web/packets/tests", "web/registration/tests", "web/challenges/tests", "web/ticketing/tests", "web/browser_tests"]
```

**Step 2: Create the directory**

```bash
mkdir -p web/browser_tests
touch web/browser_tests/__init__.py
```

**Step 3: Commit**

```bash
git add pyproject.toml web/browser_tests/__init__.py
git commit -m "Add web/browser_tests to pytest testpaths"
```

---

### Task 2: Create browser_tests/conftest.py with session injection

**Files:**
- Create: `web/browser_tests/conftest.py`

**Context:**
- `live_server` from pytest-django auto-starts Django on a random port using the test DB
- `live_server` implies `transactional_db` — data is committed and visible to the server
- Django's default session cookie name is `sessionid` (no custom SESSION_COOKIE_NAME in settings)
- `AuthentikRequiredMiddleware` in `web/core/middleware.py` redirects unauthenticated users to `/auth/login/`
- `create_user_with_groups` (from `web/conftest.py`) creates User + UserGroups + DiscordLink
- Blue team views call `get_team_from_groups()` which does `Team.objects.get(team_number=N)`, so a Team object must exist
- TicketCategory and AttackType are auto-seeded via migrations (available in test DB)

**Step 1: Write conftest.py**

```python
"""Browser test fixtures: Playwright + session injection, no OAuth required."""

import pytest
from django.test import Client
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

from core.models import UserGroups
from team.models import DiscordLink, Team

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

ALL_ROLES = [*ROLE_GROUPS.keys(), "unauthenticated"]


@pytest.fixture(scope="session")
def pw_browser():
    """Launch a single Chromium instance for the whole test session."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


def _create_role_user(role: str, db) -> "User | None":
    """Create a test user with the given role's Authentik groups + DiscordLink."""
    from django.contrib.auth.models import User

    if role == "unauthenticated":
        return None

    groups = ROLE_GROUPS[role]
    username = f"browser_test_{role}"
    user = User.objects.create_user(username=username, password="testpass123")
    UserGroups.objects.create(user=user, authentik_id=f"{username}-uid", groups=groups)

    # Blue team users need a Team + DiscordLink with team assignment
    team = None
    if role == "blue_team":
        team, _ = Team.objects.get_or_create(
            team_number=1,
            defaults={
                "team_name": "Test Team 01",
                "authentik_group": "WCComps_BlueTeam01",
                "is_active": True,
            },
        )

    DiscordLink.objects.create(
        user=user,
        discord_id=9000000 + hash(role) % 1000000,
        discord_username=username,
        team=team,
        is_active=True,
    )

    return user


def create_session_context(
    pw_browser: Browser,
    live_server: "LiveServer",
    user: "User | None",
) -> BrowserContext:
    """Create a Playwright BrowserContext with the user's session cookie injected."""
    context = pw_browser.new_context(viewport={"width": 1920, "height": 1080})

    if user is not None:
        # force_login creates a real session in the test DB
        client = Client()
        client.force_login(user)
        session_cookie = client.cookies["sessionid"]
        context.add_cookies(
            [
                {
                    "name": "sessionid",
                    "value": session_cookie.value,
                    "url": live_server.url,
                }
            ]
        )

    return context


def visit_and_capture_errors(
    context: BrowserContext,
    url: str,
) -> tuple[Page, int, list[str]]:
    """Navigate to a URL, capture console errors and page errors.

    Returns (page, status_code, errors).
    """
    page = context.new_page()
    errors: list[str] = []

    page.on(
        "console",
        lambda msg: errors.append(f"[console.error] {msg.text}")
        if msg.type == "error"
        else None,
    )
    page.on("pageerror", lambda err: errors.append(f"[pageerror] {err}"))

    response = page.goto(url, wait_until="networkidle")
    status_code = response.status if response else 0

    return page, status_code, errors
```

**Step 2: Verify conftest loads**

```bash
cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test \
  uv run pytest browser_tests/ --collect-only 2>&1 | head -20
```

Expected: no import errors, 0 tests collected (no test files yet).

**Step 3: Commit**

```bash
git add web/browser_tests/conftest.py
git commit -m "Add browser test conftest with session injection helpers"
```

---

### Task 3: Create page_registry.py

**Files:**
- Create: `web/browser_tests/page_registry.py`

**Context:**
- `AuthentikRequiredMiddleware` redirects unauthed users to `/auth/login/?next=...` (302)
- Permission-denied views return either 403, or 200 with "access denied" / "you do not have permission" in the body
- `ticket_detail` needs a Ticket object; `admin_team_detail` needs a Team; `scoring:submit_red_score` needs AttackType (auto-seeded)
- Blue team ticketing views need Team(team_number=1) to exist (created by `_create_role_user`)
- The `home` view (/) redirects to different dashboards based on role — it returns 302 for all authenticated users

**Step 1: Write page_registry.py**

```python
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
            "admin": {"present": ["form", "select[name='team']"]},
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
        allowed_roles=["unauthenticated", "blue_team", "admin"],
        denied_roles=[],
    ),
    PageDef(
        url_name="scoring:submit_red_score",
        allowed_roles=["red_team", "admin"],
        denied_roles=["blue_team", "unauthenticated"],
    ),
    PageDef(
        url_name="scoring:submit_incident_report",
        allowed_roles=["blue_team", "admin"],
        denied_roles=["unauthenticated"],
    ),
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
```

**Step 2: Verify import**

```bash
cd web && python -c "from browser_tests.page_registry import PAGES, get_allowed_test_cases; print(f'{len(PAGES)} pages, {len(get_allowed_test_cases())} allowed test cases')"
```

Expected: something like `15 pages, 35 allowed test cases`

**Step 3: Commit**

```bash
git add web/browser_tests/page_registry.py
git commit -m "Add page registry for browser role tests"
```

---

### Task 4: Create test_console_errors.py

**Files:**
- Create: `web/browser_tests/test_console_errors.py`

**Context:**
- `live_server` fixture from pytest-django starts Django on a random port; access via `live_server.url`
- `live_server` implies `transactional_db` — need to create test data in each test
- `_create_role_user` in conftest creates user + groups + team (for blue_team) + discord link
- `create_session_context` injects session cookie into Playwright context
- `visit_and_capture_errors` navigates and captures console/page errors
- Pages with `needs_data="ticket"` need a Ticket object; URL kwargs must be filled dynamically
- `django.urls.reverse()` resolves URL names to paths
- CSP is set by `SecurityHeadersMiddleware` — violations appear as console errors in the browser

**Step 1: Write the test file**

```python
"""Test that all pages render without JS or CSP console errors for each role."""

import pytest
from django.urls import reverse

from .conftest import ALL_ROLES, _create_role_user, create_session_context, visit_and_capture_errors
from .page_registry import PAGES, PageDef, get_allowed_test_cases

pytestmark = [pytest.mark.browser, pytest.mark.django_db(transaction=True)]


def _make_test_data(db):
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
    """Every allowed page×role combination should render with zero console errors."""
    test_data = _make_test_data(None)
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
```

**Step 2: Run the tests**

```bash
cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test \
  uv run pytest browser_tests/test_console_errors.py -m browser -v -n 0 --tb=long 2>&1 | tail -40
```

Expected: tests run, some may fail (revealing real CSP/JS issues). Fix any test infrastructure issues first; real failures are valuable signal.

**Step 3: Commit**

```bash
git add web/browser_tests/test_console_errors.py
git commit -m "Add console error tests: zero JS/CSP errors across all pages × roles"
```

---

### Task 5: Create test_role_ux.py

**Files:**
- Create: `web/browser_tests/test_role_ux.py`

**Context:**
- Denied roles get either 302 (redirect to login for unauthenticated) or 200 with "access denied" in body, or 403
- Element checks use Playwright's `page.locator(css).count()` to verify presence/absence
- Same `_make_test_data` and `_resolve_url` helpers as test_console_errors.py

**Step 1: Write the test file**

```python
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
    test_data = _make_test_data(None)
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
    test_data = _make_test_data(None)
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
```

**Step 2: Run the tests**

```bash
cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test \
  uv run pytest browser_tests/test_role_ux.py -m browser -v -n 0 --tb=long 2>&1 | tail -40
```

Expected: access denial tests should mostly pass. Element checks may need CSS selector tuning based on actual rendered HTML.

**Step 3: Commit**

```bash
git add web/browser_tests/test_role_ux.py
git commit -m "Add role access and element presence tests"
```

---

### Task 6: Run full browser test suite and fix issues

**Step 1: Run all browser tests**

```bash
cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test \
  uv run pytest browser_tests/ -m browser -v -n 0 --tb=long 2>&1
```

**Step 2: Triage failures**

Failures fall into two categories:

1. **Test infrastructure issues** (wrong CSS selectors, missing test data, URL resolution errors) — fix these in the test code
2. **Real CSP/JS/UX issues** — these are the valuable signal. Log them but don't fix in this task.

Iterate on Step 1-2 until all test infrastructure issues are resolved. Real failures should remain as failing tests (or be marked `xfail` with a reason if you want the suite green while you fix them).

**Step 3: Commit fixes**

```bash
git add web/browser_tests/
git commit -m "Fix browser test infrastructure issues from first run"
```

---

### Task 7: Add to deploy.sh

**Files:**
- Modify: `deploy.sh`

**Context:**
- `deploy.sh` already runs ruff, djlint, mypy, migrate, and unit tests
- Browser tests are slower (~30-60s), so run them as a separate step after fast tests pass
- Use `-n 0` to disable xdist parallelism for browser tests (Playwright manages its own concurrency)

**Step 1: Find the test command in deploy.sh and add browser tests after it**

Add after the existing pytest line:

```bash
echo "Running browser tests..."
cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test \
  uv run pytest browser_tests/ -m browser -v -n 0
```

**Step 2: Commit**

```bash
git add deploy.sh
git commit -m "Add browser tests to deploy.sh"
```
