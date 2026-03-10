# Ticket Detail Page Improvements — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve the ticket detail page layout with collapsible sections, promoted metadata, restructured status area, responsive history, and better resolve form.

**Architecture:** Modify the existing `ticket_detail.html` template and `ops_ticket_detail_dynamic.html` to restructure the status area, make fieldsets collapsible with smart defaults, and add responsive history styles. CSS changes in `app.css` for responsive history cards and status area tweaks.

**Tech Stack:** Django templates, django-cotton components, CSS, Alpine.js (existing `collapsibleFieldset` component)

**Spec:** `docs/superpowers/specs/2026-03-10-ticket-detail-improvements-design.md`

---

## Chunk 1: Template and CSS Changes

### Task 1: Restructure Status Area — Remove Pipe Separators, Two-Row Layout

**Files:**
- Modify: `web/templates/ticket_detail.html:54-120`

The current status bar crams everything into one flex-wrapped div with pipe `|` separators. Split into two rows: info row and actions row.

- [ ] **Step 1: Replace the status bar content**

In `ticket_detail.html`, replace lines 54-120 (the entire `<!-- Status bar with primary actions -->` section) with:

```html
        <!-- Status bar with primary actions -->
        <div class="status-bar">
            <!-- Row 1: Status info -->
            <div class="d-flex items-center gap-10 flex-wrap">
                {# djlint:off #}
                <c-badge variant="{% if ticket.status == 'open' %}info{% elif ticket.status == 'claimed' %}warning{% elif ticket.status == 'resolved' %}success{% else %}neutral{% endif %}">{{ status_display }}</c-badge>
                {# djlint:on #}
                {% if is_ops %}
                    {% if ticket.status == 'claimed' and ticket.assigned_to.username == authentik_username or is_ticketing_admin %}
                        <form method="post"
                              action="{% url 'ticket_change_category' ticket.ticket_number %}"
                              class="d-inline-block m-0"
                              x-data="categoryChanger"
                              data-initial-cat="{{ ticket.category_id }}"
                              @submit="confirmChange">
                            {% csrf_token %}
                            <select name="new_category"
                                    x-model="newCat"
                                    @change="submitForm"
                                    aria-label="Change ticket category"
                                    class="py-5 px-10">
                                {% for cat_id, cat_info in categories.items %}
                                    <option value="{{ cat_id }}"
                                            {% if cat_id == ticket.category_id %}selected{% endif %}>
                                        {{ cat_info.display_name }} ({{ cat_info.points }}pt)
                                    </option>
                                {% endfor %}
                            </select>
                        </form>
                    {% else %}
                        <span>{{ category_name }}</span>
                    {% endif %}
                {% else %}
                    <span>{{ category_name }}</span>
                {% endif %}
                {% if is_ops and ticket.points_charged is not None %}
                    <span>{{ ticket.points_charged }}pt charged</span>
                {% endif %}
                {% if ticket.assigned_to %}
                    <span>Assigned: {{ ticket.assigned_to }}</span>
                {% endif %}
            </div>
            <!-- Row 2: Action buttons (ops only) -->
            {% if is_ops %}
                <div class="d-flex gap-10 items-center mt-10">
                    {% if ticket.status == 'open' %}
                        <c-form action="{% url 'ticket_claim' ticket.ticket_number %}" class="m-0">
                        {% csrf_token %}
                        <c-button type="submit" variant="primary" ::disabled="submitting">Claim</c-button>
                        </c-form>
                    {% elif ticket.status == 'claimed' and ticket.assigned_to.username == authentik_username or is_ticketing_admin %}
                        <c-form action="{% url 'ticket_unclaim' ticket.ticket_number %}" class="m-0">
                        {% csrf_token %}
                        <c-button type="submit" variant="default" ::disabled="submitting">Unclaim</c-button>
                        </c-form>
                    {% endif %}
                    {% if ticket.status == 'resolved' and is_ticketing_admin %}
                        <c-form action="{% url 'ticket_reopen' ticket.ticket_number %}" class="m-0">
                        {% csrf_token %}
                        <input type="hidden" name="reopen_reason" value="">
                        <c-button type="submit" variant="warning" ::disabled="submitting">Reopen</c-button>
                        </c-form>
                    {% endif %}
                </div>
            {% endif %}
            <!-- Row 3: Key metadata (service/hostname/IP) -->
            {% if ticket.service_name or ticket.hostname or ticket.ip_address %}
                <div class="d-flex gap-10 flex-wrap mt-10 text-sm">
                    {% if ticket.service_name %}
                        <span><strong>Service:</strong> {{ ticket.service_name }}</span>
                    {% endif %}
                    {% if ticket.hostname %}
                        <span><strong>Host:</strong> {{ ticket.hostname }}</span>
                    {% endif %}
                    {% if ticket.ip_address %}
                        <span><strong>IP:</strong> {{ ticket.ip_address }}</span>
                    {% endif %}
                </div>
            {% endif %}
        </div>
```

- [ ] **Step 2: Remove promoted fields from Ticket Information fieldset**

In `ticket_detail.html`, remove the service_name, hostname, and ip_address entries from the Ticket Information fieldset (lines 179-196). The fieldset should start directly with the description `{% if %}` block. Replace lines 177-220 with:

```html
        <!-- Ticket Details -->
        <c-fieldset heading="Ticket Information">
        <c-detail_grid>
        {% if ticket.description %}
            <dt>Description</dt>
            <dd>
                {{ ticket.description }}
            </dd>
        {% endif %}
        <dt>Created</dt>
        <dd>
            {{ ticket.created_at|timesince }} ago
        </dd>
        {% if ticket.resolved_at %}
            <dt>Resolved</dt>
            <dd>
                {{ ticket.resolved_at|timesince }} ago
            </dd>
        {% endif %}
        {% if ticket.resolution_notes %}
            <dt>Resolution Notes</dt>
            <dd>
                {{ ticket.resolution_notes }}
            </dd>
        {% endif %}
        </c-detail_grid>
        </c-fieldset>
```

- [ ] **Step 3: Verify the page renders**

Run the dev server or load the page to confirm the status bar renders correctly with the three-row layout, no pipe separators, and metadata promoted.

- [ ] **Step 4: Commit**

```bash
git add web/templates/ticket_detail.html
git commit -m "Restructure ticket detail status bar and promote key metadata"
```

### Task 2: Make Sections Collapsible with Smart Defaults

**Files:**
- Modify: `web/templates/ticket_detail.html`

Convert Comments, Attachments, and History fieldsets to use `collapsible="true"` with conditional collapsed state.

- [ ] **Step 1: Make Comments fieldset collapsible**

Find the Comments fieldset line:
```html
        <c-fieldset heading="Comments">
```

Replace with:
```html
        <c-fieldset heading="Comments" collapsible="true" collapsed="{% if not comments %}true{% else %}false{% endif %}">
```

- [ ] **Step 2: Make Attachments fieldset collapsible**

Find the Attachments fieldset line:
```html
        <c-fieldset heading="Attachments">
```

Replace with:
```html
        <c-fieldset heading="Attachments" collapsible="true" collapsed="{% if not attachments %}true{% else %}false{% endif %}">
```

- [ ] **Step 3: Make History fieldset always collapsed**

Find the History fieldset line:
```html
            <c-fieldset heading="History">
```

Replace with:
```html
            <c-fieldset heading="History" collapsible="true" collapsed="true">
```

- [ ] **Step 4: Verify collapsible behavior**

Load the page and confirm:
- Comments: expanded when comments exist, collapsed when empty
- Attachments: expanded when attachments exist, collapsed when empty
- History: always collapsed initially, clicking heading expands it
- Ticket Information: stays non-collapsible (always expanded)

- [ ] **Step 5: Commit**

```bash
git add web/templates/ticket_detail.html
git commit -m "Make ticket detail sections collapsible with smart defaults"
```

### Task 3: Responsive History — Mobile Card Layout

**Files:**
- Modify: `web/static/css/app.css`
- Modify: `web/templates/ticket_detail.html` (history section)
- Modify: `web/templates/ops_ticket_detail_dynamic.html` (history section)

Add a mobile-friendly card layout for history entries that replaces the table on small screens.

- [ ] **Step 1: Add responsive history CSS to app.css**

Add the following at the end of `web/static/css/app.css`:

```css
/* ============================================
   RESPONSIVE HISTORY (ticket detail mobile)
   ============================================ */
.history-cards {
    display: none;
}

@media (max-width: 767px) {
    .history-table {
        display: none;
    }
    .history-cards {
        display: flex;
        flex-direction: column;
        gap: 8px;
    }
    .history-card {
        padding: 10px;
        background: var(--darkened-bg, #f8f8f8);
        border: 1px solid var(--hairline-color, #ddd);
        border-radius: 4px;
    }
    .history-card-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 13px;
        font-weight: 600;
        margin-bottom: 4px;
    }
    .history-card-time {
        font-size: 12px;
        color: var(--body-quiet-color, #666);
        font-weight: 400;
    }
    .history-card-details {
        font-size: 13px;
        color: var(--body-quiet-color, #666);
        margin-top: 4px;
    }
}
```

- [ ] **Step 2: Update history markup in ticket_detail.html**

Find the history section inside the History fieldset (the `{% if history %}` block within the `#history-list` div). Replace the content between `{% if history %}` and `{% else %}` with both table and card markup:

```html
                    <!-- Desktop table -->
                    <div class="history-table">
                    <c-table aria_label="Ticket history">
                    <c-slot name="headers">
                    <tr>
                        <c-table_header sortable="false">Timestamp</c-table_header>
                        <c-table_header sortable="false">Action</c-table_header>
                        <c-table_header sortable="false">Actor</c-table_header>
                        <c-table_header sortable="false">Details</c-table_header>
                    </tr>
                    </c-slot>
                    {% for event in history %}
                        <tr class="{% cycle 'row1' 'row2' %}">
                            <td>{{ event.timestamp|timesince }} ago</td>
                            <td>{{ event.action }}</td>
                            <td>
                                {% if event.actor %}
                                    {{ event.actor }}
                                {% else %}
                                    System
                                {% endif %}
                            </td>
                            <td>{{ event.details|format_history_details }}</td>
                        </tr>
                    {% endfor %}
                    </c-table>
                    </div>
                    <!-- Mobile cards -->
                    <div class="history-cards">
                    {% for event in history %}
                        <div class="history-card">
                            <div class="history-card-header">
                                <span>{{ event.action }} · {% if event.actor %}{{ event.actor }}{% else %}System{% endif %}</span>
                                <span class="history-card-time">{{ event.timestamp|timesince }} ago</span>
                            </div>
                            {% if event.details|format_history_details %}
                                <div class="history-card-details">{{ event.details|format_history_details }}</div>
                            {% endif %}
                        </div>
                    {% endfor %}
                    </div>
```

- [ ] **Step 3: Update history markup in ops_ticket_detail_dynamic.html**

Apply the same dual markup (table + cards) to the `#history-list` div in `ops_ticket_detail_dynamic.html`. Replace lines 27-56 with:

```html
<div id="history-list">
    {% if history %}
        <!-- Desktop table -->
        <div class="history-table">
        <c-table aria_label="Ticket history">
        <c-slot name="headers">
        <tr>
            <c-table_header sortable="false">Timestamp</c-table_header>
            <c-table_header sortable="false">Action</c-table_header>
            <c-table_header sortable="false">Actor</c-table_header>
            <c-table_header sortable="false">Details</c-table_header>
        </tr>
        </c-slot>
        {% for event in history %}
            <tr class="{% cycle 'row1' 'row2' %}">
                <td>{{ event.timestamp|timesince }} ago</td>
                <td>{{ event.action }}</td>
                <td>
                    {% if event.actor %}
                        {{ event.actor }}
                    {% else %}
                        System
                    {% endif %}
                </td>
                <td>{{ event.details|format_history_details }}</td>
            </tr>
        {% endfor %}
        </c-table>
        </div>
        <!-- Mobile cards -->
        <div class="history-cards">
        {% for event in history %}
            <div class="history-card">
                <div class="history-card-header">
                    <span>{{ event.action }} · {% if event.actor %}{{ event.actor }}{% else %}System{% endif %}</span>
                    <span class="history-card-time">{{ event.timestamp|timesince }} ago</span>
                </div>
                {% if event.details|format_history_details %}
                    <div class="history-card-details">{{ event.details|format_history_details }}</div>
                {% endif %}
            </div>
        {% endfor %}
        </div>
    {% else %}
        <p class="text-muted">No history available.</p>
    {% endif %}
</div>
```

- [ ] **Step 4: Verify responsive behavior**

Resize browser to mobile width (<767px) and confirm:
- History table is hidden, cards are shown
- Cards display: `action · actor` on first line, timestamp right-aligned, details below
- On desktop width, table is shown, cards are hidden

- [ ] **Step 5: Commit**

```bash
git add web/static/css/app.css web/templates/ticket_detail.html web/templates/ops_ticket_detail_dynamic.html
git commit -m "Add responsive mobile card layout for ticket history"
```

### Task 4: Resolve Form — Stack Vertically

**Files:**
- Modify: `web/templates/ticket_detail.html`

Change the resolve form from side-by-side to stacked vertical layout. Also replace the `<hr>` before reassign with a border-top div.

- [ ] **Step 1: Replace the resolve form layout**

Find the resolve form content (the `d-flex gap-20 flex-wrap items-end mb-15` div). Replace lines 127-153 with:

```html
                <div class="mb-15">
                    <div class="mb-15">
                        <label for="resolution_notes" class="font-semibold text-sm d-block mb-5">Resolution Notes:</label>
                        <textarea name="resolution_notes"
                                  id="resolution_notes"
                                  rows="3"
                                  placeholder="Describe what was done to resolve this ticket..."
                                  required
                                  class="w-full"></textarea>
                    </div>
                    <div>
                        <label for="points_override" class="font-semibold text-sm d-block mb-5">
                            {% if variable_points %}
                                Points:
                            {% else %}
                                Points Override:
                            {% endif %}
                        </label>
                        <input type="number"
                               name="points_override"
                               id="points_override"
                               placeholder="{% if variable_points %}Enter points{% else %}{{ ticket.points_charged }}pt default{% endif %}"
                               {% if variable_points %}required{% endif %}
                               min="0"
                               class="w-full">
                    </div>
                </div>
```

- [ ] **Step 2: Replace hr with border-top on reassign form**

Find:
```html
                    <hr class="my-15">
                    <c-form action="{% url 'ticket_reassign' ticket.ticket_number %}" class="d-flex gap-10 items-center m-0">
```

Replace with:
```html
                    <div class="border-top mt-15 pt-15">
                    <c-form action="{% url 'ticket_reassign' ticket.ticket_number %}" class="d-flex gap-10 items-center m-0">
```

And find the closing `</c-form>` for the reassign form followed by `{% endif %}` and `</c-fieldset>`:
```html
                    </c-form>
                {% endif %}
                </c-fieldset>
```

Replace with:
```html
                    </c-form>
                    </div>
                {% endif %}
                </c-fieldset>
```

- [ ] **Step 3: Add pt-15 utility class if missing**

Check if `pt-15` exists in `app.css`. If not, add it near the other padding utilities:

```css
.pt-15 { padding-top: 15px; }
```

- [ ] **Step 4: Verify the resolve form**

Load a claimed ticket as the assigned ops user. Confirm:
- Resolution notes textarea is full width on its own row
- Points input is below it on its own row
- Reassign section has a subtle top border instead of `<hr>`

- [ ] **Step 5: Commit**

```bash
git add web/templates/ticket_detail.html web/static/css/app.css
git commit -m "Stack resolve form vertically and replace hr with border"
```

### Task 5: Run deploy checks

**Files:** None (verification only)

- [ ] **Step 1: Run deploy.sh**

```bash
./deploy.sh
```

This runs ruff, djlint, mypy, migrations check, and tests. Fix any issues that arise.

- [ ] **Step 2: Fix any linting issues**

If djlint reformats the templates, deploy.sh will auto-commit. If ruff or mypy flag issues, fix them manually and commit.
