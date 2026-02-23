# Integration Test Design

## Goal

Add integration tests that exercise real user workflows through the Django test client, covering cross-module behavior and permission enforcement for untested apps.

## Scope

### Part 1: Gap-fill permission tests

Add `test_permissions.py` for the three apps with no permission test coverage, using the same hand-written parametrized pattern as `core/tests/test_permissions.py` and `scoring/tests/test_permissions.py`.

- **challenges**: Dashboard (orange_team + gold_team), check management (gold_team only)
- **packets**: Team packet view (blue_team), management views (gold_team only)
- **registration**: All views (gold_team only)

### Part 2: Ticket lifecycle workflow tests

End-to-end tests through the Django test client exercising the ticket state machine:

1. **Happy path**: Blue team creates ticket -> support user claims -> support user resolves
2. **Cancel flow**: Blue team creates -> blue team cancels
3. **Reopen flow**: Create -> claim -> resolve -> reopen -> reclaim -> re-resolve
4. **Invalid transitions**: Can't resolve an unclaimed ticket, can't reopen a cancelled ticket, can't claim an already-claimed ticket
5. **Cross-role**: Blue team creates, support claims, admin resolves
6. **Comments and attachments**: Add comment to ticket, upload attachment, verify access controls
7. **Bulk operations**: Bulk claim and bulk resolve multiple tickets

### Part 3: Scoring workflow tests

1. **Incident report flow**: Blue team submits incident -> gold team reviews list -> verifies it appears
2. **Red team finding flow**: Red team submits finding -> gold team sees it in review portal
3. **Inject grading flow**: White team views inject list -> grades a submission

These need `mock_quotient_client` for external API calls.

## File layout

```
web/challenges/tests/test_permissions.py         # gap-fill
web/packets/tests/test_permissions.py            # gap-fill
web/registration/tests/test_permissions.py       # gap-fill
web/ticketing/tests/__init__.py
web/ticketing/tests/test_ticket_lifecycle.py     # workflow tests
web/scoring/tests/test_workflows.py              # scoring workflow tests
```

## Non-goals

- Exhaustive permission matrix (duplicates PERMISSION_MAP without independent source of truth)
- Playwright/browser-based E2E tests (existing integration_tests/ already covers that)
- Registration templates (out of scope per project conventions)

## Patterns

- Use existing `conftest.py` role fixtures (`blue_team_user`, `ticketing_support_user`, etc.)
- Use `Client().force_login(user)` for auth
- Use `mock_quotient_client` fixture for scoring views that call external API
- Assert on status codes and observable state changes (DB records), not template content
- Create real DB objects (tickets, teams) via ORM, then exercise views against them
