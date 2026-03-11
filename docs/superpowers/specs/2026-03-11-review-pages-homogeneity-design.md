# Review Scoring Pages Homogeneity Design

## Overview

Standardize the five review/scoring pages (red team scores, orange adjustments, incidents, inject grades, ticket points) so they share consistent terminology, filters, table structure, actions, and user experience.

## Model Changes

### Field Renames

**IncidentReport** — rename four fields:
- `gold_team_reviewed` → `is_approved`
- `reviewed_by` → `approved_by` (update `related_name` from `"incidents_reviewed"` to `"incidents_approved"`)
- `reviewed_at` → `approved_at`
- `reviewer_notes` → `approval_notes`

**Ticket** — rename four fields:
- `points_verified` → `is_approved`
- `points_verified_by` → `approved_by` (update `related_name` from `"verified_tickets"` to `"approved_tickets"`)
- `points_verified_at` → `approved_at`
- `verification_notes` → `approval_notes`

All references in views, templates, services, and tests must be updated to match.

**Migration notes:**
- `IncidentReport` has a DB index on `gold_team_reviewed` that will be updated automatically by the rename migration.
- Use `RenameField` operations to preserve data (not remove + add).

### New Field

**OrangeTeamScore** — add optional FK:
- `orange_check = ForeignKey(OrangeCheck, null=True, blank=True, on_delete=SET_NULL)`
- Set in `create_orange_score_from_assignment()` when creating scores from check assignments
- Null for manual adjustments
- Used to populate the "Check Title" filter dropdown on the orange review page

## URL Changes

| Page | Current URL | New URL |
|------|------------|---------|
| Red Team | `/scoring/gold-team/red-scores/` | `/scoring/red/` |
| Orange | `/scoring/gold-team/orange/` | `/scoring/orange/` |
| Incidents | `/scoring/gold-team/incidents/` | `/scoring/incidents/` |
| Injects | `/scoring/injects/review/` | `/scoring/injects/` |
| Tickets | `/ops/review-tickets/` | No change |

## Permissions

These are intentional permission expansions from the current state. Currently all five pages require `gold_team` only (except incidents which also allows `white_team`). The new permissions allow team leads to approve their own team's work.

| Page | Permission Check | Change from current |
|------|-----------------|---------------------|
| Red Team | `red_team` OR `gold_team` | Adds red team access (explicit OR — `red_team` map doesn't include GoldTeam) |
| Orange | `orange_team` | Adds orange team access (map already includes GoldTeam) |
| Incidents | `white_team` | No change — simplifies redundant `gold_team, white_team` to just `white_team` since map includes GoldTeam |
| Injects | `white_team` | Adds white team access (map already includes GoldTeam) |
| Tickets | `ticketing_admin` OR `gold_team` | Adds gold team access (explicit OR — `ticketing_admin` map doesn't include GoldTeam) |

## Unified Page Structure

Every review page follows this layout:

### 1. Stats Bar
Three counts displayed above the filter bar:
- **Total** — unfiltered count of all items
- **Pending** — `is_approved=False`
- **Approved** — `is_approved=True`

### 2. Filter Bar
Four filters in consistent order:

1. **Status** — dropdown: Pending / Approved / All (default: Pending)
2. **Team** — dropdown populated from teams that have items
3. **Domain-specific filter** — varies by page:
   - Red Team: Attack Type (dropdown)
   - Orange: Check Title (dropdown from OrangeCheck, plus "Manual" for null)
   - Incidents: Box (text input)
   - Injects: Inject (dropdown)
   - Tickets: Category (dropdown)
4. **Search** — free-text search across relevant fields

Query parameter names: `status`, `team`, `sort`, `search`, plus domain-specific param (`attack_type`, `check`, `box`, `inject`, `category`).

### 3. Table
Consistent column ordering:

| Position | Column | Notes |
|----------|--------|-------|
| 1 | Checkbox | For bulk selection |
| 2 | ID | Clickable link to detail page |
| 3-5 | Domain columns | 2-3 columns specific to the page |
| 6 | Points | Score/points value |
| 7 | Submitted | Timesince + submitter name |
| 8 | Status | Approved/Pending badge |

Domain columns per page:

| Page | Col 3 | Col 4 | Col 5 |
|------|-------|-------|-------|
| Red Team | Attack Type | Teams | Evidence |
| Orange | Check Title | Team | Description |
| Incidents | Team | Box/Service | Evidence |
| Injects | Inject | Team | Max Points |
| Tickets | Team | Category | Resolved By |

### 4. Bulk Actions
All pages use the same Alpine.js `bulkSelect` pattern:
- Toggle-all checkbox in header
- Partial selection state (indeterminate)
- "Approve Selected" button with confirmation: "Approve {n} item(s)? This action cannot be undone."
- Success message: "Successfully approved {n} {type}."

### 5. Pagination
All pages use `c-pagination` with 50 items per page.

### 6. Empty States
Standardized messages:
- With filters: "No {items} match your filters. Try adjusting or clearing filters."
- Without filters: "No pending {items}. All {items} have been approved."

## Status Terminology

Unified across all pages:
- **Pending** — `is_approved=False`, badge `variant="claimed"` with hourglass
- **Approved** — `is_approved=True`, badge `variant="resolved"` with checkmark

## Orange Team Catch-Up

Orange is the furthest behind and needs:
1. Extract table into `cotton/review_orange_table.html`
2. Add all standard filters (status, team, check title, search)
3. Add pagination (50 per page)
4. Add checkbox bulk select with Alpine.js pattern
5. Remove per-row approve/reject buttons — use bulk approve only

## Ticket Review

Stays in `ticketing/views/ops.py` at `/ops/review-tickets/`. Changes:
- Rename fields per model changes above
- Update template terminology (Verified → Approved)
- Add standard filter bar structure
- Replace current verify dialog with checkbox bulk approve pattern
- Update permission to allow `gold_team` OR `ticketing_admin`

## Incidents Review

Keep the "Review" link on each row (links to matching/grading form) as a domain-specific action, but add checkboxes and bulk approve alongside it for quick approval of already-reviewed items.

## Out of Scope

- No changes to detail/edit pages for individual items
- No changes to submission forms (red team portal, inject grading, etc.)
- No model changes beyond the field renames and orange_check FK
- Registration templates remain out of scope
