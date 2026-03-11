# Review Scoring Pages Homogeneity Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Standardize five review/scoring pages to share consistent terminology, filters, table structure, actions, and user experience.

**Architecture:** Model field renames on IncidentReport and Ticket to use `is_approved`/`approved_by`/`approved_at` consistently. Add `orange_check` FK to OrangeTeamScore. Update all five review page views to use identical filter/sort/pagination patterns. Rewrite templates to use a common table column structure with checkbox-based bulk approve.

**Tech Stack:** Django 5.x, django-cotton components, Alpine.js (CSP build), HTMX

**Spec:** `docs/superpowers/specs/2026-03-11-review-pages-homogeneity-design.md`

---

## Chunk 1: Model Migrations

### Task 1: Rename IncidentReport fields

**Files:**
- Modify: `web/scoring/models.py:530-553` (IncidentReport fields)
- Modify: `web/scoring/models.py:564-567` (Meta indexes)
- Create: new migration in `web/scoring/migrations/`

- [ ] **Step 1: Rename fields in the model**

In `web/scoring/models.py`, rename these four fields on the `IncidentReport` class:

```python
# Line 530: gold_team_reviewed -> is_approved
is_approved = models.BooleanField(default=False)

# Line 545: reviewer_notes -> approval_notes
approval_notes = models.TextField(blank=True)

# Line 546-551: reviewed_by -> approved_by, update related_name
approved_by = models.ForeignKey(
    User,
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="incidents_approved",
)

# Line 553: reviewed_at -> approved_at
approved_at = models.DateTimeField(null=True, blank=True)
```

Also update the index in `Meta.indexes` (line 566):
```python
models.Index(fields=["is_approved"]),
```

- [ ] **Step 2: Generate migration**

Run: `cd web && uv run python manage.py makemigrations scoring --name rename_incident_approval_fields`

Expected: New migration file created with `RenameField` operations.

- [ ] **Step 3: Verify migration uses RenameField**

Read the generated migration file and confirm it uses `migrations.RenameField` (not `RemoveField` + `AddField`) for all four renames. Django should auto-detect renames, but verify.

- [ ] **Step 4: Apply migration locally**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run python manage.py migrate scoring`

Expected: Migration applied successfully.

- [ ] **Step 5: Commit**

```
git add web/scoring/models.py web/scoring/migrations/
git commit -m "Rename IncidentReport review fields to is_approved/approved_by/approved_at"
```

### Task 2: Rename Ticket fields

**Files:**
- Modify: `web/ticketing/models.py:107-117` (Ticket fields)
- Create: new migration in `web/ticketing/migrations/`

- [ ] **Step 1: Rename fields in the model**

In `web/ticketing/models.py`, rename these four fields on the `Ticket` class:

```python
# Line 108: points_verified -> is_approved
is_approved = models.BooleanField(default=False)

# Line 109-114: points_verified_by -> approved_by, update related_name
approved_by = models.ForeignKey(
    "auth.User",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="approved_tickets",
)

# Line 116: points_verified_at -> approved_at
approved_at = models.DateTimeField(null=True, blank=True)

# Line 117: verification_notes -> approval_notes
approval_notes = models.TextField(blank=True)
```

Update the section comment (line 107):
```python
# Approval (admin review)
```

- [ ] **Step 2: Generate migration**

Run: `cd web && uv run python manage.py makemigrations ticketing --name rename_ticket_approval_fields`

- [ ] **Step 3: Verify migration uses RenameField**

Read the generated migration and confirm `RenameField` operations.

- [ ] **Step 4: Apply migration locally**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run python manage.py migrate ticketing`

- [ ] **Step 5: Commit**

```
git add web/ticketing/models.py web/ticketing/migrations/
git commit -m "Rename Ticket verification fields to is_approved/approved_by/approved_at"
```

### Task 3: Add OrangeTeamScore.orange_check FK

**Files:**
- Modify: `web/scoring/models.py:702-763` (OrangeTeamScore)
- Modify: `web/challenges/services.py:66-74` (create_orange_score_from_assignment)
- Create: new migration in `web/scoring/migrations/`

- [ ] **Step 1: Add FK field to OrangeTeamScore**

In `web/scoring/models.py`, add after the `approved_by` field (around line 749):

```python
orange_check = models.ForeignKey(
    "challenges.OrangeCheck",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="orange_scores",
    help_text="Orange check this score was created from (null for manual adjustments)",
)
```

- [ ] **Step 2: Update create_orange_score_from_assignment**

In `web/challenges/services.py`, update the `OrangeTeamScore.objects.create()` call (line 66-74) to include the FK:

```python
return OrangeTeamScore.objects.create(
    team=assignment.team,
    submitted_by=assignment.user,
    description=f"Check: {assignment.orange_check.title}",
    points_awarded=assignment.score or 0,
    is_approved=True,
    approved_by=approver,
    approved_at=timezone.now(),
    orange_check=assignment.orange_check,
)
```

- [ ] **Step 3: Generate and apply migration**

Run: `cd web && uv run python manage.py makemigrations scoring --name add_orange_check_fk && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run python manage.py migrate scoring`

- [ ] **Step 4: Commit**

```
git add web/scoring/models.py web/scoring/migrations/ web/challenges/services.py
git commit -m "Add OrangeTeamScore.orange_check FK for filter support"
```

---

## Chunk 2: Update All References to Renamed Fields

### Task 4: Update IncidentReport field references

All files that reference the old IncidentReport field names must be updated. The renamed fields are:
- `gold_team_reviewed` → `is_approved`
- `reviewed_by` → `approved_by`
- `reviewed_at` → `approved_at`
- `reviewer_notes` → `approval_notes`

**Files to update (grep results):**

- [ ] **Step 1: Update `web/scoring/views/incidents.py`**

All references:
- Line 146: `incident.gold_team_reviewed` → `incident.is_approved`
- Line 168: `incident.gold_team_reviewed` → `incident.is_approved`
- Line 219: `gold_team_reviewed=False` → `is_approved=False`
- Line 221: `gold_team_reviewed=True` → `is_approved=True`
- Line 254: `gold_team_reviewed=True` → `is_approved=True`
- Line 295: `incident.gold_team_reviewed = True` → `incident.is_approved = True`
- Line 296: `incident.reviewed_by` → `incident.approved_by`
- Line 297: `incident.reviewed_at` → `incident.approved_at`

- [ ] **Step 2: Update `web/scoring/calculator.py`**

Search for and replace any `gold_team_reviewed` or `reviewed_by`/`reviewed_at` references.

- [ ] **Step 3: Update `web/scoring/export.py`**

Replace field name references in export functions.

- [ ] **Step 4: Update `web/scoring/forms.py`**

Replace any references to `reviewer_notes` in form fields.

- [ ] **Step 5: Update `web/scoring/admin.py`**

Replace field references in admin class configuration.

- [ ] **Step 6: Update templates**

Update these template files:
- `web/templates/scoring/view_incident.html`: `incident.gold_team_reviewed` → `incident.is_approved`, `incident.reviewer_notes` → `incident.approval_notes`, `incident.reviewed_by` → `incident.approved_by`, `incident.reviewed_at` → `incident.approved_at`
- `web/templates/scoring/incident_list.html`: `incident.gold_team_reviewed` → `incident.is_approved`
- `web/templates/scoring/match_incident.html`: `incident.gold_team_reviewed` → `incident.is_approved`, `incident.reviewed_by` → `incident.approved_by`, `incident.reviewed_at` → `incident.approved_at`
- `web/templates/cotton/review_incidents_table.html`: `incident.gold_team_reviewed` → `incident.is_approved`

- [ ] **Step 7: Update `web/scoring/management/commands/import_qualifier_scores.py`**

Replace field name references.

- [ ] **Step 8: Update `web/challenges/views.py` and `web/challenges/models.py`**

Replace any references to `gold_team_reviewed`, `reviewed_by`, `reviewed_at`.

- [ ] **Step 9: Update test files**

Update these test files:
- `web/scoring/tests/test_export.py`
- `web/scoring/tests/test_scoring.py`
- `web/challenges/tests/test_lead.py`

- [ ] **Step 10: Run tests to verify**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest -x`

Expected: All tests pass.

- [ ] **Step 11: Commit**

```
git add -A
git commit -m "Update all IncidentReport field references to new names"
```

### Task 5: Update Ticket field references

All files that reference the old Ticket field names must be updated. The renamed fields are:
- `points_verified` → `is_approved`
- `points_verified_by` → `approved_by`
- `points_verified_at` → `approved_at`
- `verification_notes` → `approval_notes`

**Files to update (grep results):**

- [ ] **Step 1: Update `web/ticketing/views/ops.py`**

All references:
- Line 56: `points_verified_by` in select_related → `approved_by`
- Line 59: `points_verified=True` → `is_approved=True`
- Line 61: `points_verified=False` → `is_approved=False`
- Line 154: `verification_notes` variable → `approval_notes`
- Line 166-169: `ticket.points_verified`, `ticket.points_verified_by`, `ticket.points_verified_at`, `ticket.verification_notes` → `ticket.is_approved`, `ticket.approved_by`, `ticket.approved_at`, `ticket.approval_notes`
- Line 176: `action="points_verified"` → keep as-is (this is a TicketHistory action string, not a field)
- Line 179: `"verification_notes"` in dict → `"approval_notes"`
- Line 203: `points_verified=False` → `is_approved=False`
- Line 209-210: `ticket.points_verified`, `ticket.points_verified_by`, `ticket.points_verified_at` → `ticket.is_approved`, `ticket.approved_by`, `ticket.approved_at`

- [ ] **Step 2: Update `web/ticketing/templatetags/ticket_filters.py`**

Replace any `points_verified` references.

- [ ] **Step 3: Update templates**

Update these template files:
- `web/templates/ops_review_tickets.html`: `verified_filter` → `status_filter`, `points_verified` terminology
- `web/templates/cotton/review_tickets_table.html`: `item.ticket.points_verified` → `item.ticket.is_approved`, `item.ticket.points_verified_by` → `item.ticket.approved_by`

- [ ] **Step 4: Update test files**

Update these test files:
- `web/core/tests/test_ticket_workflow.py`
- `web/core/tests/test_batch_ticket_approval.py`

- [ ] **Step 5: Run tests to verify**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest -x`

Expected: All tests pass.

- [ ] **Step 6: Commit**

```
git add -A
git commit -m "Update all Ticket field references to new names"
```

---

## Chunk 3: URL Changes and Permission Updates

### Task 6: Update scoring URLs

**Files:**
- Modify: `web/scoring/urls.py`

- [ ] **Step 1: Update URL paths**

Change these URL patterns in `web/scoring/urls.py`:

```python
# Line 19: gold-team/red-scores/ -> red/
path("red/", views.red_team_portal, name="red_team_portal"),

# Line 48: gold-team/incidents/ -> incidents/
path("incidents/", views.review_incidents, name="review_incidents"),

# Line 49: gold-team/incidents/<int:incident_id>/match/ -> incidents/<int:incident_id>/match/
path("incidents/<int:incident_id>/match/", views.match_incident, name="match_incident"),

# Line 51: gold-team/orange/ -> orange/
path("orange/", views.review_orange, name="review_orange"),

# Line 45: injects/review/ -> injects/ (note: keep injects/ for inject_grading, rename to injects/grading/)
path("injects/grading/", views.inject_grading, name="inject_grading"),
path("injects/", views.inject_grades_review, name="inject_grades_review"),
```

Note: The existing `path("injects/", views.inject_grading, ...)` at line 44 conflicts with the new `injects/` for review. Rename inject_grading to `injects/grading/`.

- [ ] **Step 2: Run tests to verify URL changes don't break anything**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest -x`

- [ ] **Step 3: Commit**

```
git add web/scoring/urls.py
git commit -m "Update review page URLs to /scoring/red/, /scoring/orange/, etc."
```

### Task 7: Update permissions on review views

**Files:**
- Modify: `web/scoring/views/red_team.py:52-55`
- Modify: `web/scoring/views/orange.py:23`
- Modify: `web/scoring/views/injects.py:106`
- Modify: `web/ticketing/views/ops.py:28-36`
- Modify: `web/scoring/views/red_team.py:228-231` (bulk approve)
- Modify: `web/scoring/views/orange.py:35,67` (approve/bulk approve)
- Modify: `web/scoring/views/injects.py:236` (bulk approve)

- [ ] **Step 1: Update red team portal permission**

In `web/scoring/views/red_team.py`, change the decorator on `red_team_portal` (line 52-55):

```python
@require_permission(
    "red_team", "gold_team",
    error_message="Only Red Team or Gold Team members can review findings",
)
```

Also update `bulk_approve_red_scores` (line 228-231):
```python
@require_permission(
    "red_team", "gold_team",
    error_message="Only Red Team or Gold Team members can approve findings",
)
```

- [ ] **Step 2: Update orange review permission**

In `web/scoring/views/orange.py`, change `review_orange` (line 23):
```python
@require_permission("orange_team", error_message="Only Orange Team or Gold Team members can review checks")
```

Also update all approve/reject/bulk views (lines 35, 51, 67, 97) to use `"orange_team"`.

- [ ] **Step 3: Update inject grades review permission**

In `web/scoring/views/injects.py`, change `inject_grades_review` (line 106):
```python
@require_permission("white_team", error_message="Only White Team or Gold Team members can review inject grades")
```

Also update `inject_grades_bulk_approve` (line 236):
```python
@require_permission("white_team", error_message="Only White Team or Gold Team members can approve inject grades")
```

- [ ] **Step 4: Update ticket review permission**

In `web/ticketing/views/ops.py`, change `ops_review_tickets` (line 22-36) to use the decorator pattern instead of manual check:

```python
@require_permission("ticketing_admin", "gold_team", error_message="Only Ticketing Admins or Gold Team can review tickets")
def ops_review_tickets(request: HttpRequest) -> HttpResponse:
    """Review resolved tickets for point approval (admin only)."""
    # Remove the manual permission check (lines 25-36)
    ...
```

Also update `ops_verify_ticket` (line 130) and `ops_batch_verify_tickets` (line 191) similarly.

- [ ] **Step 5: Run tests**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest -x`

- [ ] **Step 6: Commit**

```
git add web/scoring/views/red_team.py web/scoring/views/orange.py web/scoring/views/injects.py web/ticketing/views/ops.py
git commit -m "Update review page permissions per design spec"
```

---

## Chunk 4: Standardize Red Team Review Page

### Task 8: Update red team review terminology and filters

**Files:**
- Modify: `web/scoring/views/red_team.py:56-145`
- Modify: `web/templates/scoring/review_red_findings.html`
- Modify: `web/templates/cotton/red_findings_table.html`

- [ ] **Step 1: Update status filter values in view**

In `web/scoring/views/red_team.py`, the `red_team_portal` function:
- Line 75: Change `status_filter == "reviewed"` → `status_filter == "approved"`
- Add search filter support:

```python
search_query = request.GET.get("search", "").strip()
```

After existing filters (around line 88), add:
```python
if search_query:
    from django.db.models import Q
    base_query = base_query.filter(
        Q(attack_type__name__icontains=search_query)
        | Q(notes__icontains=search_query)
        | Q(affected_service__icontains=search_query)
    )
```

Add `search_query` to context dict and pass `"search_query": search_query`.

Rename context key `"reviewed_count"` → `"approved_count"`.

- [ ] **Step 2: Update red findings template filters**

In `web/templates/scoring/review_red_findings.html`:
- Line 37-38: Change status option `value="reviewed"` text from "Reviewed Only" → "Approved Only", condition from `status_filter == 'reviewed'` → `status_filter == 'approved'`
- Add search filter field after the Submitter filter (before closing `</c-filter_toolbar>`):

```html
<c-filter_field label="Search" id="id_search" min_width="180px">
<input type="text"
       name="search"
       id="id_search"
       value="{{ search_query }}"
       placeholder="Search..."
       aria-label="Search findings">
</c-filter_field>
```

- [ ] **Step 3: Update red findings table status badge**

In `web/templates/cotton/red_findings_table.html`:
- Line 108: Change "Reviewed" → "Approved" in the badge text

- [ ] **Step 4: Update empty state messages**

In `web/templates/cotton/red_findings_table.html`:
- Line 142: Change to "No findings to review. No pending findings."
- Add search_query to the filter check condition

- [ ] **Step 5: Update pagination query_params**

In `web/templates/cotton/red_findings_table.html` line 151, add `&search={{ search_query }}` to the pagination query_params.

Also update sort header query_params (lines 43, 47) to include `&search={{ search_query }}`.

- [ ] **Step 6: Run tests**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest -x`

- [ ] **Step 7: Commit**

```
git add web/scoring/views/red_team.py web/templates/scoring/review_red_findings.html web/templates/cotton/red_findings_table.html
git commit -m "Standardize red team review: terminology, search filter"
```

---

## Chunk 5: Standardize Orange Team Review Page

### Task 9: Rewrite orange review view with filters, pagination, bulk approve

The orange review page needs the most work — it currently has no filters, no pagination, no HTMX, and an inline table.

**Files:**
- Modify: `web/scoring/views/orange.py:23-27`
- Rewrite: `web/templates/scoring/review_orange.html`
- Create: `web/templates/cotton/review_orange_table.html`

- [ ] **Step 1: Rewrite the review_orange view**

Replace the `review_orange` function in `web/scoring/views/orange.py` (lines 23-27) with a full view matching the pattern from red_team_portal:

```python
@require_permission("orange_team", error_message="Only Orange Team or Gold Team members can review checks")
def review_orange(request: HttpRequest) -> HttpResponse:
    """Review page for orange team checks."""
    from django.core.paginator import Paginator
    from django.db.models import Q

    from challenges.models import OrangeCheck

    status_filter = request.GET.get("status", "pending") or "pending"
    team_filter = request.GET.get("team", "")
    check_filter = request.GET.get("check", "")
    search_query = request.GET.get("search", "").strip()
    sort_by = request.GET.get("sort", "-created_at")
    if sort_by == "default":
        sort_by = ""
    page = request.GET.get("page", "1")

    base_query = OrangeTeamScore.objects.select_related(
        "team", "submitted_by", "approved_by", "orange_check"
    )

    # Apply status filter
    if status_filter == "pending":
        base_query = base_query.filter(is_approved=False)
    elif status_filter == "approved":
        base_query = base_query.filter(is_approved=True)

    # Apply team filter
    if team_filter:
        base_query = base_query.filter(team__id=team_filter)

    # Apply check filter
    if check_filter:
        if check_filter == "manual":
            base_query = base_query.filter(orange_check__isnull=True)
        else:
            try:
                base_query = base_query.filter(orange_check_id=int(check_filter))
            except (ValueError, TypeError):
                pass

    # Apply search
    if search_query:
        base_query = base_query.filter(
            Q(description__icontains=search_query)
        )

    # Validate and apply sort
    valid_sort_fields = [
        "created_at", "-created_at",
        "team__team_number", "-team__team_number",
        "points_awarded", "-points_awarded",
    ]
    if sort_by and sort_by not in valid_sort_fields:
        sort_by = "-created_at"
    if sort_by:
        base_query = base_query.order_by(sort_by)

    # Pagination
    paginator = Paginator(base_query, 50)
    try:
        page_num = int(page)
    except ValueError:
        page_num = 1
    page_obj = paginator.get_page(page_num)

    # Stats (unfiltered counts)
    total_checks = OrangeTeamScore.objects.count()
    pending_count = OrangeTeamScore.objects.filter(is_approved=False).count()
    approved_count = total_checks - pending_count

    # Filter dropdown options
    from team.models import Team
    available_teams = Team.objects.filter(orange_team_scores__isnull=False).distinct().order_by("team_number")
    available_checks = OrangeCheck.objects.filter(orange_scores__isnull=False).distinct().order_by("title")

    context = {
        "page_obj": page_obj,
        "total_checks": total_checks,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "has_pending": pending_count > 0,
        "available_teams": available_teams,
        "available_checks": available_checks,
        "selected_team": team_filter,
        "selected_check": check_filter,
        "search_query": search_query,
        "status_filter": status_filter,
        "sort_by": sort_by,
    }

    if request.headers.get("HX-Request"):
        return render(request, "cotton/review_orange_table.html", context)

    return render(request, "scoring/review_orange.html", context)
```

- [ ] **Step 2: Update bulk_approve_orange_adjustments**

Update the redirect target in `bulk_approve_orange_adjustments` (line 76, 94) from `"scoring:orange_team_portal"` → `"scoring:review_orange"`. Also update in `reject_orange_adjustment` (line 48, 64).

Also update `approve_orange_adjustment` redirect (line 48).

- [ ] **Step 3: Rewrite the orange review template**

Rewrite `web/templates/scoring/review_orange.html` to match the pattern from `review_red_findings.html`:

```html
{% extends "scoring/base.html" %}
{% load cotton %}
{% block title %}
    Review Orange Team Checks
{% endblock title %}
{% block scoring_content %}
    <script>
    document.addEventListener('alpine:init', () => {
        Alpine.data('orangeBulkSelect', () => ({
            selected: [],
            selectableIds: [],
            submitting: false,
            init() { this.selectableIds = Array.from(this.$el.querySelectorAll('[data-check-id]')).map(el => el.dataset.checkId); },
            get allSelected() { return this.selected.length === this.selectableIds.length && this.selectableIds.length > 0; },
            get someSelected() { return this.selected.length > 0 && this.selected.length < this.selectableIds.length; },
            toggleAll() { this.selected = this.allSelected ? [] : [...this.selectableIds]; },
            submitBulk() {
                if (this.submitting) return;
                if (this.selected.length === 0) { alert('Please select at least one check to approve'); return; }
                if (confirm('Approve ' + this.selected.length + ' check(s)? This action cannot be undone.')) { this.submitting = true; this.$refs.bulkForm.submit(); }
            }
        }));
    });
    </script>
    <c-page_header title="Review Orange Team Checks" />
    <c-module filtered="true" id="changelist">
    <c-filter_toolbar form_id="changelist-filter" hx_get="{% url 'scoring:review_orange' %}" hx_target="#review-orange-content" hx_swap="outerHTML" hx_push_url="true">
    {% if has_pending %}
        <c-slot name="actions">
        <c-button type="button" onclick="document.dispatchEvent(new CustomEvent('bulk-approve-orange'))" variant="primary">Approve Selected</c-button>
        </c-slot>
    {% endif %}
    <c-filter_field label="Status" id="id_status">
    <select name="status" id="id_status" aria-label="Filter by status">
        <option value="pending" {% if status_filter == 'pending' %}selected{% endif %}>Pending Only</option>
        <option value="approved" {% if status_filter == 'approved' %}selected{% endif %}>Approved Only</option>
        <option value="all" {% if status_filter == 'all' %}selected{% endif %}>All</option>
    </select>
    </c-filter_field>
    <c-filter_field label="Team" id="id_team">
    <select name="team" id="id_team" aria-label="Filter by team">
        <option value="">All Teams</option>
        {% for team in available_teams %}
            <option value="{{ team.id }}" {% if selected_team == team.id|stringformat:"s" %}selected{% endif %}>
                Team {{ team.team_number }}
            </option>
        {% endfor %}
    </select>
    </c-filter_field>
    <c-filter_field label="Check" id="id_check">
    <select name="check" id="id_check" aria-label="Filter by check">
        <option value="">All Checks</option>
        <option value="manual" {% if selected_check == 'manual' %}selected{% endif %}>Manual</option>
        {% for check in available_checks %}
            <option value="{{ check.id }}" {% if selected_check == check.id|stringformat:"s" %}selected{% endif %}>
                {{ check.title }}
            </option>
        {% endfor %}
    </select>
    </c-filter_field>
    <c-filter_field label="Search" id="id_search" min_width="180px">
    <input type="text" name="search" id="id_search" value="{{ search_query }}" placeholder="Search..." aria-label="Search checks">
    </c-filter_field>
    </c-filter_toolbar>
    <c-review_orange_table :page_obj="page_obj" :status_filter="status_filter" :selected_team="selected_team" :selected_check="selected_check" :search_query="search_query" :sort_by="sort_by" />
    </c-module>
{% endblock scoring_content %}
```

- [ ] **Step 4: Create the orange table cotton component**

Create `web/templates/cotton/review_orange_table.html`:

```html
{# Orange team checks review table - swappable content for htmx #}
<div {{ attrs }}
     id="review-orange-content"
     x-data="orangeBulkSelect"
     @bulk-approve-orange.document="submitBulk">
    <form id="bulk-approve-form"
          method="post"
          action="{% url 'scoring:bulk_approve_orange_adjustments' %}"
          x-ref="bulkForm">
        {% csrf_token %}
        <div class="results">
            <table id="result_list" role="grid" aria-label="Orange team checks list">
                <thead>
                    <tr role="row">
                        <th scope="col" class="w-40">
                            <input type="checkbox"
                                   :checked="allSelected"
                                   :indeterminate="someSelected"
                                   @click="toggleAll"
                                   title="Select all">
                        </th>
                        <c-table_header sortable="false">ID</c-table_header>
                        <c-table_header sortable="false">Check</c-table_header>
                        <c-table_header sort_field="team__team_number" current_sort=sort_by query_params="&status={{ status_filter }}&team={{ selected_team }}&check={{ selected_check }}&search={{ search_query }}">Team</c-table_header>
                        <c-table_header sortable="false">Description</c-table_header>
                        <c-table_header sort_field="points_awarded" current_sort=sort_by query_params="&status={{ status_filter }}&team={{ selected_team }}&check={{ selected_check }}&search={{ search_query }}">Points</c-table_header>
                        <c-table_header sort_field="created_at" current_sort=sort_by query_params="&status={{ status_filter }}&team={{ selected_team }}&check={{ selected_check }}&search={{ search_query }}">Submitted</c-table_header>
                        <c-table_header sortable="false">Status</c-table_header>
                    </tr>
                </thead>
                <tbody>
                    {% for check in page_obj %}
                        <tr class="{% cycle 'row1' 'row2' %}" role="row">
                            <td>
                                {% if not check.is_approved %}
                                    <input type="checkbox"
                                           name="adjustment_ids"
                                           value="{{ check.id }}"
                                           data-check-id="{{ check.id }}"
                                           x-model="selected">
                                {% endif %}
                            </td>
                            <th class="field-id">
                                <strong>#{{ check.id }}</strong>
                            </th>
                            <td class="field-check">
                                {% if check.orange_check %}
                                    {{ check.orange_check.title }}
                                {% else %}
                                    <span class="text-muted">Manual</span>
                                {% endif %}
                            </td>
                            <td class="field-team">Team {{ check.team.team_number }}</td>
                            <td class="field-description">{{ check.description|truncatechars:60 }}</td>
                            <td class="field-points text-right">
                                <c-score_value :value="check.points_awarded" format="signed" />
                            </td>
                            <td class="field-submitted">
                                {{ check.created_at|timesince }} ago
                                <div class="text-sm text-muted">by {{ check.submitted_by.username }}</div>
                            </td>
                            <td class="field-status">
                                {% if check.is_approved %}
                                    <c-badge variant="resolved"><span aria-hidden="true">✓</span> Approved</c-badge>
                                    {% if check.approved_by %}
                                        <div class="text-sm text-muted">by {{ check.approved_by.username }}</div>
                                    {% endif %}
                                {% else %}
                                    <c-badge variant="claimed"><span aria-hidden="true">⏳</span> Pending</c-badge>
                                {% endif %}
                            </td>
                        </tr>
                    {% empty %}
                        <tr>
                            <td colspan="8" class="text-center p-20">
                                {% if selected_team or selected_check or search_query or status_filter != 'pending' %}
                                    No checks match your filters. Try <a href="{% url 'scoring:review_orange' %}">clearing all filters</a>
                                {% else %}
                                    No pending checks. All orange team checks have been approved.
                                {% endif %}
                            </td>
                        </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </form>
    <c-pagination :page_obj="page_obj" query_params="&status={{ status_filter }}&team={{ selected_team }}&check={{ selected_check }}&search={{ search_query }}&sort={{ sort_by }}" />
</div>
```

- [ ] **Step 5: Remove reject views and URLs**

Remove `reject_orange_adjustment` and `bulk_reject_orange_adjustments` from `web/scoring/views/orange.py`.

Remove the corresponding URL patterns from `web/scoring/urls.py` (lines 40, 42):
```python
# Remove these:
path("orange-team/<int:adjustment_id>/reject/", ...),
path("orange-team/bulk-reject/", ...),
```

Also remove the individual `approve_orange_adjustment` view and URL (lines 38-39) since approval is now bulk-only.

- [ ] **Step 6: Run tests**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest -x`

- [ ] **Step 7: Commit**

```
git add web/scoring/views/orange.py web/templates/scoring/review_orange.html web/templates/cotton/review_orange_table.html web/scoring/urls.py
git commit -m "Standardize orange review: filters, pagination, bulk approve, HTMX"
```

---

## Chunk 6: Standardize Incidents and Injects Review Pages

### Task 10: Update incidents review with bulk approve and search

**Files:**
- Modify: `web/scoring/views/incidents.py:199-276`
- Modify: `web/templates/scoring/review_incidents.html`
- Modify: `web/templates/cotton/review_incidents_table.html`

- [ ] **Step 1: Add search filter and bulk approve URL to incidents view**

In `web/scoring/views/incidents.py`, update `review_incidents`:
- Add `search_query = request.GET.get("search", "").strip()` to filter params
- Add search filter after box_filter:
```python
if search_query:
    from django.db.models import Q
    base_query = base_query.filter(
        Q(attack_description__icontains=search_query)
        | Q(affected_service__icontains=search_query)
    )
```
- Rename `reviewed_count` → `approved_count` in context (line 254, 263)
- Add `"search_query": search_query` and `"has_pending": pending_count > 0` to context

- [ ] **Step 2: Update incidents template — add search, bulk approve button, fix terminology**

In `web/templates/scoring/review_incidents.html`:
- Add Alpine.js `bulkSelect` script block (same pattern as red team)
- Change status filter options: "Reviewed Only" → "Approved Only", value `"reviewed"` → `"approved"`
- Add search filter field
- Add bulk approve button in `<c-slot name="actions">`

- [ ] **Step 3: Update incidents table — add checkboxes, fix terminology**

In `web/templates/cotton/review_incidents_table.html`:
- Wrap in `x-data="incidentsBulkSelect"` and `@bulk-approve-incidents.document="submitBulk"`
- Add bulk approve form wrapping the table
- Add checkbox column in header and rows (for unapproved incidents)
- Line 39-40: Change `incident.gold_team_reviewed` → `incident.is_approved`
- Line 40: Change "Reviewed" badge → "Approved"
- Line 51-52: Change `incident.gold_team_reviewed` → `incident.is_approved`
- Keep the "Review" link for individual incident matching
- Update empty state messages
- Add search_query to pagination query_params

- [ ] **Step 4: Create bulk approve view for incidents**

Add to `web/scoring/views/incidents.py`:

```python
@require_permission("white_team", error_message="Only White Team or Gold Team members can approve incidents")
@transaction.atomic
@require_http_methods(["POST"])
def bulk_approve_incidents(request: HttpRequest) -> HttpResponse:
    """Bulk approve incident reports."""
    user = cast(User, request.user)
    incident_ids = request.POST.getlist("incident_ids")

    if not incident_ids:
        messages.info(request, "No incidents selected for approval")
        return redirect("scoring:review_incidents")

    valid_ids = []
    for iid in incident_ids:
        try:
            valid_ids.append(int(iid))
        except (ValueError, TypeError):
            continue

    if not valid_ids:
        messages.warning(request, "No valid incident IDs provided")
        return redirect("scoring:review_incidents")

    now = timezone.now()
    approved_count = 0
    for incident in IncidentReport.objects.filter(id__in=valid_ids, is_approved=False):
        incident.is_approved = True
        incident.approved_by = user
        incident.approved_at = now
        incident.save()
        approved_count += 1

    if approved_count > 0:
        messages.success(request, f"Successfully approved {approved_count} incident(s)")
    else:
        messages.info(request, "No unapproved incidents found to approve")

    return redirect("scoring:review_incidents")
```

- [ ] **Step 5: Add URL for bulk approve incidents**

Add to `web/scoring/urls.py`:
```python
path("incidents/bulk-approve/", views.bulk_approve_incidents, name="bulk_approve_incidents"),
```

Also add `bulk_approve_incidents` to `web/scoring/views/__init__.py` imports.

- [ ] **Step 6: Run tests**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest -x`

- [ ] **Step 7: Commit**

```
git add web/scoring/views/incidents.py web/scoring/views/__init__.py web/scoring/urls.py web/templates/scoring/review_incidents.html web/templates/cotton/review_incidents_table.html
git commit -m "Standardize incidents review: bulk approve, search, terminology"
```

### Task 11: Update inject grades review — add search, fix terminology

**Files:**
- Modify: `web/scoring/views/injects.py:107-233`
- Modify: `web/templates/scoring/review_inject_grades.html`
- Modify: `web/templates/cotton/inject_grades_table.html`

- [ ] **Step 1: Add search to inject grades view**

In `web/scoring/views/injects.py`, in `inject_grades_review`:
- Add `search_query = request.GET.get("search", "").strip()` to filter params
- Add search filter:
```python
if search_query:
    from django.db.models import Q
    base_query = base_query.filter(
        Q(inject_name__icontains=search_query)
        | Q(inject_id__icontains=search_query)
    )
```
- Add `"search_query": search_query` to context

- [ ] **Step 2: Add search filter to inject grades template**

In `web/templates/scoring/review_inject_grades.html`, add search field after the Outliers filter:
```html
<c-filter_field label="Search" id="id_search" min_width="180px">
<input type="text" name="search" id="id_search" value="{{ search_query }}" placeholder="Search..." aria-label="Search grades">
</c-filter_field>
```

- [ ] **Step 3: Update inject grades table pagination and sort query_params**

Add `&search={{ search_query }}` to all query_params in `web/templates/cotton/inject_grades_table.html` (sort headers and pagination).

- [ ] **Step 4: Run tests**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest -x`

- [ ] **Step 5: Commit**

```
git add web/scoring/views/injects.py web/templates/scoring/review_inject_grades.html web/templates/cotton/inject_grades_table.html
git commit -m "Add search filter to inject grades review"
```

---

## Chunk 7: Standardize Tickets Review Page

### Task 12: Update ticket review — terminology, checkbox bulk approve

**Files:**
- Modify: `web/ticketing/views/ops.py`
- Modify: `web/templates/ops_review_tickets.html`
- Modify: `web/templates/cotton/review_tickets_table.html`

- [ ] **Step 1: Update ticket review view filter parameter names**

In `web/ticketing/views/ops.py`, `ops_review_tickets`:
- Line 39: Change `verified_filter` → `status_filter`, param name `"verified"` → `"status"`, default `"unverified"` → `"pending"`
- Line 58-61: Update filter conditions to use `status_filter` variable and new values:
```python
if status_filter == "approved":
    query = query.filter(is_approved=True)
elif status_filter == "pending":
    query = query.filter(is_approved=False)
```
- Rename context key `"verified_filter"` → `"status_filter"`
- Remove `"page_size"` from context (standardize to 50)
- Remove page_size filter logic (lines 45-53)

- [ ] **Step 2: Add category dropdown filter**

In the view, add category filter:
```python
category_filter = request.GET.get("category", "")
if category_filter:
    query = query.filter(category_id=category_filter)
```
Add `"category_filter": category_filter` to context.

- [ ] **Step 3: Rewrite ticket review template**

Rewrite `web/templates/ops_review_tickets.html` to match the standard pattern:
- Add Alpine.js `ticketsBulkSelect` script
- Change filter bar: Status (Pending/Approved/All), Team dropdown, Category dropdown, Search
- Replace "Approve All Unverified" button with "Approve Selected" bulk button
- Remove `showVerificationDialog` JavaScript
- Remove Results Per Page filter

- [ ] **Step 4: Rewrite ticket review table**

Rewrite `web/templates/cotton/review_tickets_table.html`:
- Add `x-data="ticketsBulkSelect"` wrapper
- Add checkbox column
- Update status badge: "Verified" → "Approved", `item.ticket.points_verified` → `item.ticket.is_approved`, `item.ticket.points_verified_by` → `item.ticket.approved_by`
- Remove per-row verify button/form
- Update query_params: `verified=` → `status=`, remove `page_size`
- Update empty states: "unverified" → "pending", "verified" → "approved"

- [ ] **Step 5: Update batch verify to be checkbox-based**

Rewrite `ops_batch_verify_tickets` in `web/ticketing/views/ops.py` to accept `ticket_ids` from POST (checkbox-based) instead of approving all:

```python
@require_permission("ticketing_admin", "gold_team", error_message="Only Ticketing Admins or Gold Team can approve tickets")
@transaction.atomic
@require_http_methods(["POST"])
def ops_batch_verify_tickets(request: HttpRequest) -> HttpResponse:
    """Bulk approve selected ticket points."""
    user = cast(User, request.user)
    ticket_ids = request.POST.getlist("ticket_ids")

    if not ticket_ids:
        messages.info(request, "No tickets selected for approval")
        return redirect("ops_review_tickets")

    valid_ids = []
    for tid in ticket_ids:
        try:
            valid_ids.append(int(tid))
        except (ValueError, TypeError):
            continue

    now = timezone.now()
    approved_count = 0
    for ticket in Ticket.objects.filter(id__in=valid_ids, is_approved=False, status="resolved"):
        ticket.is_approved = True
        ticket.approved_by = user
        ticket.approved_at = now
        ticket.save()

        TicketHistory.objects.create(
            ticket=ticket,
            action="points_verified",
            details={
                "verified_by": user.username,
                "points_charged": ticket.points_charged,
            },
        )
        approved_count += 1

    if approved_count > 0:
        messages.success(request, f"Successfully approved {approved_count} ticket(s)")

    return redirect("ops_review_tickets")
```

- [ ] **Step 6: Run tests**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest -x`

- [ ] **Step 7: Commit**

```
git add web/ticketing/views/ops.py web/templates/ops_review_tickets.html web/templates/cotton/review_tickets_table.html
git commit -m "Standardize ticket review: terminology, checkbox bulk approve, filters"
```

---

## Chunk 8: Final Verification and Cleanup

### Task 13: Run full deploy checks and fix any issues

- [ ] **Step 1: Run deploy checks**

Run: `cd /home/ubuntu/wccomps-bot && ./deploy.sh`

This runs ruff, djlint, mypy, migrations, and tests. Fix any failures.

- [ ] **Step 2: Fix any ruff/djlint/mypy issues**

Address any linting or type checking failures from deploy.sh.

- [ ] **Step 3: Fix any test failures**

If tests fail, diagnose and fix the issues.

- [ ] **Step 4: Verify all five pages visually**

Check that all review pages are accessible and render correctly:
- `/scoring/red/`
- `/scoring/orange/`
- `/scoring/incidents/`
- `/scoring/injects/`
- `/ops/review-tickets/`

- [ ] **Step 5: Final commit if needed**

```
git add -A
git commit -m "Fix linting and type check issues from review pages homogeneity"
```
