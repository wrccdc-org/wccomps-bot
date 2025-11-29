# UI Design System

## Overview

This document defines consistent UI patterns for WCComps. The system builds on Django Admin CSS with Cotton components for reusable UI elements.

---

## Design Principles

1. **Consistency** - Same patterns across all pages
2. **Role-Based** - UI adapts to user permissions
3. **Minimal** - Only show what's needed
4. **Accessible** - Semantic HTML, proper labels, keyboard navigation

---

## Color Palette

### Semantic Colors

| Name | Hex | Usage |
|------|-----|-------|
| **Primary** | `#417690` | Links, headers, primary actions, info states |
| **Success** | `#388e3c` | Success messages, positive scores, approved states |
| **Warning** | `#f57c00` | Warnings, pending states, claimed tickets |
| **Danger** | `#ba2121` | Errors, deletions, negative scores, rejected states |
| **Info** | `#1976d2` | Open tickets, informational badges |

### Background Colors

| State | Background | Border | Text |
|-------|------------|--------|------|
| **Success** | `#e8f5e9` | `#388e3c` | `#388e3c` |
| **Warning** | `#fff3cd` | `#ffc107` | `#856404` |
| **Danger** | `#ffebee` | `#ba2121` | `#ba2121` |
| **Info** | `#e8f4f8` | `#417690` | `#417690` |
| **Neutral** | `#f5f5f5` | `#ddd` | `#666` |

### Score Colors

| Context | Color | Usage |
|---------|-------|-------|
| **Positive** | `#28a745` | Point gains, bonuses |
| **Negative** | `#dc3545` | Point deductions, penalties |
| **Neutral** | `#666` | Base scores, unchanged values |

---

## Typography

### Hierarchy

| Element | Size | Weight | Color | Usage |
|---------|------|--------|-------|-------|
| Page Title | 24px | 400 | `#333` | Via `<c-page_header>` |
| Section Header | 18px | 600 | `#333` | `<h2>` in modules |
| Subsection | 16px | 600 | `#333` | `<h3>` in fieldsets |
| Body | 14px | 400 | `#333` | Default text |
| Small/Help | 12px | 400 | `#666` | Help text, timestamps |
| Monospace | 13px | 400 | `#333` | Code, IPs, technical data |

### Font Stack

```css
font-family: "Segoe UI", system-ui, Roboto, "Helvetica Neue", Arial, sans-serif;
font-family: ui-monospace, "Cascadia Code", "Source Code Pro", Menlo, Consolas, monospace; /* code */
```

---

## Spacing Scale

| Name | Value | Usage |
|------|-------|-------|
| `xs` | 5px | Tight spacing, badge padding |
| `sm` | 10px | Form field gaps, list item padding |
| `md` | 15px | Section gaps, card padding |
| `lg` | 20px | Module padding, major sections |
| `xl` | 30px | Page sections, large gaps |

---

## Layout Patterns

### Page Structure

```
┌─────────────────────────────────────────────────────────┐
│ Header (branding, user menu)                            │
├─────────────────────────────────────────────────────────┤
│ Primary Navigation (role-based links)                   │
├─────────────────────────────────────────────────────────┤
│ Sub-Navigation (context-specific, e.g., scoring tabs)   │
├─────────────────────────────────────────────────────────┤
│ Page Header (title + optional subtitle)                 │
├─────────────────────────────────────────────────────────┤
│ Content Module(s)                                       │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Module Toolbar (back link, actions)                 │ │
│ ├─────────────────────────────────────────────────────┤ │
│ │ Module Content (forms, tables, details)             │ │
│ └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

### Grid Layouts

| Pattern | Columns | Usage |
|---------|---------|-------|
| Stats Grid | 3 equal | Dashboard metrics |
| Detail Grid | 2 equal | Two-column detail views |
| Form Grid | 1 column | Form fields (stacked) |
| Table | Full width | Data lists |

---

## Components

### Existing Cotton Components

#### `<c-page_header>`

Page title with optional subtitle.

```django
<c-page_header title="Review Incidents" subtitle="Match incidents to red findings" />
```

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `title` | string | required | Main heading (h1) |
| `subtitle` | string | - | Secondary text below title |

---

#### `<c-module>`

Content container with optional toolbar and filtering.

```django
<c-module id="changelist" filtered="true">
  <c-slot name="toolbar">
    <c-link href="/back" variant="history">Back</c-link>
  </c-slot>
  Content here
</c-module>
```

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `id` | string | - | DOM id for styling hooks |
| `filtered` | boolean | false | Adds filter styling class |

| Slot | Purpose |
|------|---------|
| `toolbar` | Action links, buttons at top |
| default | Main content area |

---

#### `<c-fieldset>`

Groups form fields with optional heading.

```django
<c-fieldset heading="Contact Information" aligned="true">
  <c-form_field label="Email" required="true">
    <input type="email" name="email" />
  </c-form_field>
</c-fieldset>
```

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `heading` | string | - | Section title (h2) |
| `aligned` | boolean | false | Enables aligned form layout |

---

#### `<c-form_field>`

Single form field with label, help text, and error display.

```django
<c-form_field label="Title" required="true" help_text="Brief description">
  <input type="text" name="title" id="id_title" />
</c-form_field>
```

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `label` | string | required | Field label |
| `required` | boolean | false | Shows required indicator |
| `help_text` | string | - | Help text below field |
| `errors` | list | - | Error messages to display |

---

#### `<c-button>`

Styled action button.

```django
<c-button type="submit" variant="primary">Save</c-button>
<c-button type="button" variant="danger">Delete</c-button>
<c-button type="button" variant="cancel" href="/cancel">Cancel</c-button>
```

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `type` | string | "button" | Button type (submit, button, reset) |
| `variant` | string | "default" | Style variant |
| `href` | string | - | If provided, renders as link |
| `disabled` | boolean | false | Disables button |

| Variant | Appearance | Usage |
|---------|------------|-------|
| `default` | Standard button | Secondary actions |
| `primary` | Blue background | Primary actions |
| `danger` | Red text/border | Destructive actions |
| `cancel` | Gray, subtle | Cancel/back actions |

---

#### `<c-link>`

Styled link with icon variants.

```django
<c-link href="/add" variant="addlink">Add New</c-link>
<c-link href="/back" variant="history">Back to List</c-link>
<c-link href="/edit" variant="change">Edit</c-link>
```

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `href` | string | required | Link URL |
| `variant` | string | "default" | Style variant |

| Variant | Icon | Usage |
|---------|------|-------|
| `default` | None | Standard link |
| `addlink` | Plus (+) | Add/create actions |
| `change` | Pencil | Edit actions |
| `history` | Arrow (←) | Back/history links |
| `delete` | X | Delete actions |

---

#### `<c-alert>`

Message display for feedback.

```django
<c-alert variant="success">Changes saved successfully.</c-alert>
<c-alert variant="error">
  <strong>Validation Errors:</strong>
  <ul>{% for e in errors %}<li>{{ e }}</li>{% endfor %}</ul>
</c-alert>
```

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `variant` | string | "info" | Alert type |

| Variant | Colors | Usage |
|---------|--------|-------|
| `info` | Blue | Informational messages |
| `success` | Green | Success confirmations |
| `warning` | Yellow/orange | Warnings, cautions |
| `error` | Red | Errors, validation failures |

---

#### `<c-badge>`

Status indicator badge.

```django
<c-badge status="open">Open</c-badge>
<c-badge status="resolved">Resolved</c-badge>
```

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `status` | string | required | Badge type |

| Status | Colors | Usage |
|--------|--------|-------|
| `open` | Blue | Open/new items |
| `claimed` | Orange | In-progress items |
| `resolved` | Green | Completed items |
| `cancelled` | Gray | Cancelled/closed items |

**Note**: Use badges only for status indicators, not for counts or labels.

---

#### `<c-table>`

Data table with accessibility features.

```django
<c-table id="result_list" aria_label="Team list" fixed_layout="true">
  <c-slot name="headers">
    <tr>
      <th scope="col"><div class="text">Team</div></th>
      <th scope="col"><div class="text">Status</div></th>
    </tr>
  </c-slot>
  {% for item in items %}
  <tr class="{% cycle 'row1' 'row2' %}">
    <td>{{ item.name }}</td>
    <td>{{ item.status }}</td>
  </tr>
  {% endfor %}
</c-table>
```

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `id` | string | - | Table ID |
| `aria_label` | string | - | Accessibility label |
| `fixed_layout` | boolean | false | Use fixed column widths |

| Slot | Purpose |
|------|---------|
| `headers` | Table header row(s) |
| default | Table body rows |

---

#### `<c-table_header>`

Sortable column header.

```django
<c-table_header sort_field="created_at" current_sort="-created_at" min_width="100px">
  Created
</c-table_header>
```

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `sort_field` | string | required | Field name for sorting |
| `current_sort` | string | - | Current sort field (prefix `-` for desc) |
| `min_width` | string | - | Minimum column width |

---

#### `<c-pagination>`

Page navigation for lists.

```django
<c-pagination
  page="{{ page_obj.number }}"
  total_pages="{{ page_obj.paginator.num_pages }}"
  has_previous="{{ page_obj.has_previous }}"
  has_next="{{ page_obj.has_next }}"
  previous_page="{{ page_obj.previous_page_number }}"
  next_page="{{ page_obj.next_page_number }}" />
```

---

#### `<c-filter_toolbar>`

Container for filter/search controls.

```django
<c-filter_toolbar>
  <c-filter_field label="Search">
    <input type="text" name="q" value="{{ request.GET.q }}" />
  </c-filter_field>
  <c-filter_field label="Status">
    <select name="status">...</select>
  </c-filter_field>
</c-filter_toolbar>
```

---

#### `<c-filter_field>`

Individual filter input in toolbar.

```django
<c-filter_field label="Team">
  <select name="team">...</select>
</c-filter_field>
```

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `label` | string | - | Field label |

---

### Proposed New Components

#### `<c-stats_card>` (to create)

Dashboard metric display.

```django
<c-stats_card value="42" label="Pending Reviews" color="primary" />
```

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `value` | string | required | Large number/value |
| `label` | string | required | Description text |
| `color` | string | "primary" | Value color (primary, success, warning, danger) |

Replaces inline grid styling in dashboard pages.

---

#### `<c-detail_grid>` (to create)

Two-column detail layout.

```django
<c-detail_grid>
  <c-slot name="left">
    <h3>Attack Details</h3>
    ...
  </c-slot>
  <c-slot name="right">
    <h3>Target Information</h3>
    ...
  </c-slot>
</c-detail_grid>
```

Replaces inline grid CSS in detail pages.

---

#### `<c-empty_state>` (to create)

Empty list/no results display.

```django
<c-empty_state
  icon="inbox"
  title="No incidents found"
  description="Incidents will appear here when submitted." />
```

---

#### `<c-nav>` (to create)

Sub-navigation tabs.

```django
<c-nav current="leaderboard">
  <c-nav_item name="leaderboard" href="{% url 'scoring:leaderboard' %}">Leaderboard</c-nav_item>
  <c-nav_item name="red_team" href="{% url 'scoring:red_team' %}" condition="{{ user.is_gold_team }}">
    Review Red Team
  </c-nav_item>
</c-nav>
```

Replaces pipe-separated breadcrumb navigation.

---

#### `<c-score_value>` (to create)

Formatted score display with color.

```django
<c-score_value value="{{ points }}" />  {# Auto-colors based on +/- #}
<c-score_value value="{{ points }}" format="signed" />  {# Shows +/- prefix #}
```

---

## Page Patterns

### List Page

```django
{% extends "base.html" %}

{% block content %}
<div id="content-main">
  <c-page_header title="Tickets" />

  <c-module id="changelist" filtered="true">
    <c-slot name="toolbar">
      <c-link href="/tickets/create" variant="addlink">Create Ticket</c-link>
    </c-slot>

    <c-filter_toolbar>
      <c-filter_field label="Status">
        <select name="status">...</select>
      </c-filter_field>
    </c-filter_toolbar>

    <c-table aria_label="Ticket list">
      <c-slot name="headers">
        <tr>
          <c-table_header sort_field="id">ID</c-table_header>
          <th scope="col"><div class="text">Status</div></th>
        </tr>
      </c-slot>
      {% for ticket in tickets %}
      <tr class="{% cycle 'row1' 'row2' %}">
        <td>{{ ticket.id }}</td>
        <td><c-badge status="{{ ticket.status }}">{{ ticket.status }}</c-badge></td>
      </tr>
      {% empty %}
      <tr><td colspan="2">No tickets found.</td></tr>
      {% endfor %}
    </c-table>

    <c-pagination ... />
  </c-module>
</div>
{% endblock %}
```

---

### Detail Page

```django
{% extends "base.html" %}

{% block content %}
<div id="content-main">
  <c-page_header title="Ticket #{{ ticket.id }}" />

  <c-module>
    <c-slot name="toolbar">
      <c-link href="/tickets" variant="history">Back to Tickets</c-link>
    </c-slot>

    <c-alert variant="info">Status: {{ ticket.status }}</c-alert>

    <c-fieldset heading="Ticket Details">
      <table class="detail-table">
        <tr><th>Team:</th><td>{{ ticket.team }}</td></tr>
        <tr><th>Category:</th><td>{{ ticket.category }}</td></tr>
        <tr><th>Created:</th><td>{{ ticket.created_at }}</td></tr>
      </table>
    </c-fieldset>
  </c-module>
</div>
{% endblock %}
```

---

### Form Page

```django
{% extends "base.html" %}

{% block content %}
<div id="content-main">
  <c-page_header title="Create Ticket" />

  <c-module>
    <c-slot name="toolbar">
      <c-link href="/tickets" variant="history">Back to Tickets</c-link>
    </c-slot>

    {% if form.errors %}
    <c-alert variant="error">Please correct the errors below.</c-alert>
    {% endif %}

    <form method="POST">
      {% csrf_token %}
      <c-fieldset heading="Ticket Information" aligned="true">
        <c-form_field label="Title" required="true" errors="{{ form.title.errors }}">
          {{ form.title }}
        </c-form_field>
        <c-form_field label="Category" required="true">
          {{ form.category }}
        </c-form_field>
        <c-form_field label="Description" required="true" help_text="Describe your issue">
          {{ form.description }}
        </c-form_field>
      </c-fieldset>

      <div class="submit-row">
        <c-button type="submit" variant="primary">Create Ticket</c-button>
        <c-link href="/tickets" variant="cancel">Cancel</c-link>
      </div>
    </form>
  </c-module>
</div>
{% endblock %}
```

---

### Dashboard Page

```django
{% extends "base.html" %}

{% block content %}
<div id="content-main">
  <c-page_header title="Review Dashboard" />

  <c-module>
    <div class="stats-grid">
      <c-stats_card value="{{ pending_count }}" label="Pending Review" color="warning" />
      <c-stats_card value="{{ approved_count }}" label="Approved" color="success" />
      <c-stats_card value="{{ rejected_count }}" label="Rejected" color="danger" />
    </div>
  </c-module>

  <c-module>
    <c-slot name="toolbar">
      <h2>Recent Items</h2>
    </c-slot>
    <c-table>...</c-table>
  </c-module>
</div>
{% endblock %}
```

---

## Form Guidelines

### Standard Approach

Use Cotton components (`<c-fieldset>`, `<c-form_field>`) for all forms:

```django
<form method="POST">
  {% csrf_token %}
  <c-fieldset heading="Section Name" aligned="true">
    <c-form_field label="Field" required="true" help_text="Help">
      {{ form.field }}
    </c-form_field>
  </c-fieldset>
  <div class="submit-row">
    <c-button type="submit" variant="primary">Save</c-button>
  </div>
</form>
```

### When to Use Crispy Forms

Only for complex dynamic forms where field order/visibility changes based on model.

### Form Layout Rules

1. One column layout (fields stacked)
2. Labels above inputs (aligned mode)
3. Required indicator on required fields
4. Help text below inputs
5. Error messages below inputs in red
6. Submit button row at bottom

---

## Table Guidelines

### Structure

```django
<c-table id="result_list" aria_label="Description" fixed_layout="true">
  <colgroup>
    <col style="width: 10%;">
    <col style="width: 30%;">
    <col style="width: 60%;">
  </colgroup>
  <c-slot name="headers">
    <tr>
      <th scope="col"><div class="text">ID</div></th>
      <th scope="col"><div class="text">Name</div></th>
      <th scope="col"><div class="text">Description</div></th>
    </tr>
  </c-slot>
  {% for item in items %}
  <tr class="{% cycle 'row1' 'row2' %}">
    <td>{{ item.id }}</td>
    <td>{{ item.name }}</td>
    <td>{{ item.description }}</td>
  </tr>
  {% endfor %}
</c-table>
```

### Column Width Guidelines

| Content Type | Width |
|--------------|-------|
| Checkbox | 5% |
| ID/Number | 8-10% |
| Status badge | 10-12% |
| Short text (name) | 15-20% |
| Email | 20-25% |
| Description | 30-40% |
| Actions | 10-15% |
| Timestamp | 15% |

### Row Styling

- Alternate row colors: `{% cycle 'row1' 'row2' %}`
- Field-specific classes: `class="field-status"`
- Numeric alignment: `style="text-align: right;"`

---

## Navigation Guidelines

### Primary Navigation

Rendered in header based on user roles. Links only shown if user has permission.

### Sub-Navigation (Scoring)

Use `<c-nav>` component (when created) instead of pipe separators:

```django
<c-nav current="{{ current_page }}">
  <c-nav_item name="leaderboard" href="...">Leaderboard</c-nav_item>
  {% if user.is_gold_team %}
  <c-nav_item name="red_team" href="...">Review Red Team</c-nav_item>
  {% endif %}
</c-nav>
```

### Current Page Indicator

- Bold text
- Brighter color (`#fff` instead of `#c4dce8`)
- No underline on hover

---

## Accessibility Requirements

1. All tables have `aria-label`
2. All form inputs have associated `<label>`
3. Required fields marked with `required` attribute and visual indicator
4. Color not sole indicator of meaning (pair with text/icon)
5. Sufficient color contrast (4.5:1 minimum)
6. Keyboard navigation for all interactive elements
7. Focus indicators visible

---

## Known Issues to Address

### High Priority

- [ ] Extract inline styles to component CSS
- [ ] Create `<c-nav>` component for sub-navigation
- [ ] Create `<c-stats_card>` component
- [ ] Standardize all forms to use Cotton (remove mixed crispy usage)
- [ ] Fix `<c-badge>` misuse (status only, not counts)

### Medium Priority

- [ ] Create `<c-detail_grid>` component
- [ ] Create `<c-empty_state>` component
- [ ] Create `<c-score_value>` component
- [ ] Consolidate color definitions into CSS custom properties
- [ ] Add missing `aria-label` to tables

### Low Priority

- [ ] Create CSS utility classes for common spacing
- [ ] Document icon usage patterns
- [ ] Create component storybook/examples page

---

## Migration Notes

When updating existing templates:

1. Replace `<div class="module">` with `<c-module>`
2. Replace inline alert divs with `<c-alert variant="...">`
3. Replace raw `<table>` with `<c-table>` (add `aria-label`)
4. Replace pipe-separated nav with `<c-nav>` when available
5. Replace inline grid styling with layout components when available
6. Move inline styles to component-level CSS blocks
