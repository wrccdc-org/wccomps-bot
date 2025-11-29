# WCComps Implementation Tasks

Remaining tasks to bring codebase into conformance with specification documents.

---

## Summary

| Priority | Remaining | Description |
|----------|-----------|-------------|
| P2 | 2 | UI polish tasks |
| P3 | 2 | Documentation |

---

## Remaining Tasks

### UI Polish (P2)

**UI-8**: Audit non-scoring templates for missing aria-labels on tables.

**UI-10**: Extract remaining inline styles to utility classes.

---

### Documentation (P3)

**DOC-1**: Add quick start guide for each role to README.

**DOC-2**: Document REST endpoints in `docs/api.md`.

---

## Completed Tasks

### P0 - Critical (All Done)
- ✅ PERM-1: Restrict Leaderboard Access
- ✅ PERM-2: Add Missing Role Flags (`is_white_team`, `is_orange_team`)
- ✅ PERM-3: Conditional Navigation Visibility
- ✅ PERM-4: Filter Orange Team Portal to Own Submissions
- ✅ PERM-5: Primary Navigation with Role Conditionals
- ✅ BUG-1: Fix inject_grading.html Template Error

### P1 - High (All Done)
- ✅ MODEL-1: Approval Fields on RedTeamFinding
- ✅ MODEL-2: Check Type Field on OrangeTeamBonus
- ✅ MODEL-3: Approval Fields on OrangeTeamBonus
- ✅ MODEL-4: Approval Fields on InjectGrade
- ✅ MODEL-5: Incident-Finding Matching Support
- ✅ FEAT-1: Blue Team Incident List View
- ✅ FEAT-2: Red Team Finding Filters
- ✅ FEAT-3: Bulk Approve Red Team Findings
- ✅ FEAT-4: Bulk Approve Orange Adjustments
- ✅ FEAT-5: Bulk Approve Inject Grades
- ✅ FEAT-6: Ticket Point Approval Workflow
- ✅ FEAT-7: Data Export Functionality
- ✅ FEAT-8: Team Registration Flow
- ✅ FEAT-9: Competition Lifecycle (managed via Discord bot)

### P2 - Medium (Most Done)
- ✅ UI-1: `<c-nav>` Component
- ✅ UI-2: `<c-stats_card>` Component
- ✅ UI-3: `<c-detail_grid>` Component
- ✅ UI-4: `<c-empty_state>` Component
- ✅ UI-5: `<c-score_value>` Component
- ✅ UI-6: Fix Template Field Reference Error
- ✅ UI-7: Convert `registration/register.html` to Cotton fieldset (removed crispy-forms dependency)
- ✅ UI-9: Migrate Sub-Navigation to `<c-nav>`
- ✅ TEST-1: Permission Integration Tests (`scoring/tests/test_permissions.py`, `core/tests/test_permissions.py`)
- ✅ TEST-2: Workflow Integration Tests (`scoring/tests/test_workflows.py`, `core/tests/test_ticket_workflow.py`)
- ✅ TEST-3: Export Functionality Tests (`scoring/tests/test_export.py`)
