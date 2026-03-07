# Browser-Based Role Testing

## Problem

1. CSP violations and JS errors go unnoticed until manually hitting pages
2. Only admin role is regularly tested manually — broken layouts/missing elements for blue team, red team, ops, etc. go undetected
3. No automated way to catch visual/functional regressions across roles

## Solution

Playwright + Django LiveServer + session injection. Real browser catches CSP/JS errors, `force_login` + cookie injection avoids OAuth dependency, parametrized across all roles.

## Architecture

New test directory `web/browser_tests/`, separate from unit and integration tests:

```
web/browser_tests/
├── conftest.py              # Session injection fixtures, console error capture
├── page_registry.py         # Central page × role × expected elements definitions
├── test_console_errors.py   # Zero JS/CSP errors across all pages × roles
└── test_role_ux.py          # Role-specific element and access assertions
```

Uses `pytest-django`'s `live_server` fixture (auto-starts Django on random port, uses test DB with auto-rollback). No Authentik, no `.env.test`, same `docker-compose.test.yml` as existing tests. Marker: `@pytest.mark.browser`.

## Session Injection

1. Create user with `create_user_with_groups` (existing fixture)
2. `Client().force_login(user)` creates a real DB session
3. Extract `sessionid` cookie from Django client
4. Set cookie in Playwright browser context
5. Playwright browses as that user — no OAuth needed

## Console Error Capture

Each page visit attaches listeners before navigation:
- `page.on("console", ...)` captures CSP violations and console errors
- `page.on("pageerror", ...)` captures uncaught JS exceptions
- After `wait_until="networkidle"`, assert zero errors collected

## Roles Tested

All major roles, each with its own fixture creating a user with appropriate Authentik groups:

| Role | Group(s) |
|------|----------|
| blue_team | WCComps_BlueTeam01 |
| red_team | WCComps_RedTeam |
| gold_team | WCComps_GoldTeam |
| orange_team | WCComps_OrangeTeam |
| white_team | WCComps_WhiteTeam |
| ticketing_support | WCComps_Ticketing_Support |
| ticketing_admin | WCComps_Ticketing_Admin |
| admin | WCComps_Discord_Admin |
| unauthenticated | (no session cookie) |

## Page Registry

Central `PageDef` dataclass defining what to test per page:

```python
@dataclass
class PageDef:
    url_name: str           # Django URL name
    url_kwargs: dict        # Args for reverse()
    setup: str | None       # Fixture name for required test data
    allowed_roles: list     # Roles that should get 200
    denied_roles: list      # Roles that should get 302/403
    checks: dict            # Role → {present: [...], absent: [...]} CSS selectors
```

Adding a new page = adding one `PageDef` entry. No new test functions needed.

## Initial Page Coverage

| Page | Roles | Reason |
|------|-------|--------|
| ticket_list | blue_team, ticketing_support, admin | Heavy role-conditional UI |
| create_ticket | blue_team, admin | Alpine.js dropdown, cotton components |
| ticket_detail | blue_team, ticketing_support, admin | Action buttons vary by role |
| admin_competition | gold_team, admin | Admin dashboard |
| admin_teams | gold_team, admin | Team list |
| admin_team_detail | gold_team, admin | Team detail with actions |
| home | all roles | Role-based redirect |
| scoring:leaderboard | unauthenticated, blue_team, admin | Public page |
| scoring:submit_red_score | red_team | Alpine.js form |
| scoring:submit_incident_report | blue_team, admin | File upload form |
| challenges:dashboard | orange_team, gold_team | Check-in UI |
| packets:team_packet | blue_team | Packet list |

Registration templates are out of scope.

## Test Data

- Teams: session-scoped fixture creating a few teams (or running `init_teams`)
- TicketCategory and AttackType: auto-seeded via migrations
- Per-page fixtures: `create_test_ticket`, `create_test_red_score` for pages needing objects

## Three Parametrized Tests

1. **`test_no_console_errors[page × role]`** — zero JS/CSP errors on every allowed page for every role
2. **`test_role_access[page × role]`** — allowed roles get 200, denied roles get redirect/403
3. **`test_role_elements[page × role]`** — expected CSS selectors present/absent per role

## Execution

```bash
# Standalone
cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test \
  uv run pytest browser_tests/ -m browser -v

# Parallelized via pytest-xdist (-n auto)
```

Integrates into `deploy.sh` as a separate step after fast unit tests. Failure output includes page name, role, and the specific browser error.
