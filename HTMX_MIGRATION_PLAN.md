# htmx Migration Plan

## Overview

Migrate from vanilla JavaScript to htmx for server-interaction patterns. Keep Alpine.js or vanilla JS for client-only UI state.

## Prerequisites

1. Add htmx to base template
2. Create partial templates for swappable regions
3. Add Django views that return partials

## Phase 1: Filter Auto-Submit (High Value)

These pages reload entirely when filters change. htmx enables partial table updates.

### 1.1 ops_review_tickets.html
**Current JS:** 100+ lines - debounced search, auto-submit on filter change, cursor position restore
**htmx approach:**
```html
<form hx-get="{% url 'ops_review_tickets' %}"
      hx-trigger="change, input delay:500ms from:#id_search"
      hx-target="#ticket-table"
      hx-swap="outerHTML">
```
**Partial needed:** `ops_review_tickets_table.html` (just the table)
**Complexity:** Medium - need to preserve search focus

### 1.2 team_tickets.html
**Current JS:** 10 lines - auto-submit on status change
**htmx approach:**
```html
<select hx-get="{% url 'team_tickets' %}"
        hx-trigger="change"
        hx-target="#result_list"
        hx-include="[name='status']">
```
**Partial needed:** `team_tickets_table.html`
**Complexity:** Low

### 1.3 scoring/red_team_portal.html
**Current JS:** Filter auto-submit + select all checkboxes
**htmx approach:** Same pattern as above for filters
**Keep as JS:** Select all checkbox logic
**Partial needed:** `red_team_portal_table.html`
**Complexity:** Medium

### 1.4 scoring/orange_team_portal.html
**Current JS:** Select all checkboxes only
**htmx approach:** None needed - keep JS for checkbox logic
**Complexity:** N/A

## Phase 2: Content Swap on Selection (Medium Value)

### 2.1 scoring/inject_grading.html
**Current JS:** 15 lines - redirect on inject selection
**htmx approach:**
```html
<select hx-get="{% url 'scoring:inject_grading' %}"
        hx-trigger="change"
        hx-target="#grading-content"
        hx-vals="js:{inject: this.value}">
```
**Partial needed:** `inject_grading_content.html` (form + table)
**Complexity:** Low

## Phase 3: Auto-Refresh (Medium Value)

### 3.1 base.html (leaderboard refresh)
**Current JS:** `setInterval(location.reload, 30000)`
**htmx approach:**
```html
<div hx-get="{% url 'current_page' %}"
     hx-trigger="every 30s"
     hx-target="#content-main"
     hx-swap="innerHTML">
```
**Consideration:** Only active on specific pages, not all pages
**Complexity:** Low - but need conditional logic for which pages auto-refresh

## Phase 4: Confirmation Dialogs (Low Value)

### 4.1 packets/ops_packet_detail.html
**Current JS:** 8 lines - confirm before action
**htmx approach:**
```html
<button hx-post="{% url 'action' %}"
        hx-confirm="Are you sure?">
```
**Complexity:** Low
**Value:** Minimal - current approach works fine

## Phase 5: Keep as JavaScript (No Migration)

These patterns don't benefit from htmx:

### 5.1 create_ticket.html
**Why:** Dynamic form field show/hide based on category selection is purely client-side. No server round-trip needed.
**Alternative:** Could use Alpine.js for cleaner syntax, but current JS works.

### 5.2 ops_review_tickets.html - Verification Dialog
**Why:** Multi-step prompt() and confirm() dialogs with user input. htmx can't replace browser dialogs.
**Alternative:** Could build modal component, but significantly more work.

### 5.3 Bulk Checkbox Operations
**Files:** ops_ticket_list.html, ops_review_tickets.html, orange_team_portal.html, red_team_portal.html
**Why:** Select all/none is client-side state management.
**Alternative:** Alpine.js `x-model` would be cleaner.

### 5.4 scoring/submit_*.html Forms
**Files:** submit_incident.html, submit_orange_bonus.html, submit_red_finding.html
**Why:** Dynamic field filtering (services by hostname) is client-side.
**Alternative:** Could fetch services via htmx on hostname change, but adds latency.

## Implementation Order

| Priority | Template | Effort | Impact |
|----------|----------|--------|--------|
| 1 | team_tickets.html | Low | Medium - simple win, proves pattern |
| 2 | inject_grading.html | Low | Medium - removes page reload |
| 3 | ops_review_tickets.html (filters only) | Medium | High - most complex filter page |
| 4 | red_team_portal.html (filters only) | Medium | Medium |
| 5 | base.html auto-refresh | Low | Low - polish |
| 6 | ops_packet_detail.html confirms | Low | Low - polish |

## Template Structure Changes

### Before (full page)
```
templates/
  team_tickets.html          # Full page with table
```

### After (with partials)
```
templates/
  team_tickets.html          # Full page, includes partial
  partials/
    team_tickets_table.html  # Just the table for htmx swap
```

### View Changes

```python
# Before
def team_tickets(request):
    return render(request, 'team_tickets.html', context)

# After
def team_tickets(request):
    template = 'team_tickets.html'
    if request.headers.get('HX-Request'):
        template = 'partials/team_tickets_table.html'
    return render(request, template, context)
```

## htmx Setup

### base.html addition
```html
<script src="https://unpkg.com/htmx.org@2.0.4"></script>
```

### Optional extensions
- `hx-boost` - progressively enhance all links (probably overkill)
- `response-targets` - different targets for error responses

## Estimated Effort

- Phase 1: 4-6 hours (partials + view changes + testing)
- Phase 2: 1-2 hours
- Phase 3: 1 hour
- Phase 4: 30 minutes
- Total: ~8-10 hours

## Success Metrics

1. Reduced JS lines (target: 50% reduction in filter-related JS)
2. Faster perceived performance (partial updates vs full reload)
3. Preserved functionality (all existing features work)

## Risks

1. **htmx + existing JS conflicts** - Mitigate by testing each migration independently
2. **Back button behavior** - htmx modifies URL with `hx-push-url`, need to handle
3. **Error handling** - Need consistent partial error responses
4. **CSRF tokens** - htmx includes them automatically with `hx-headers` or Django middleware
