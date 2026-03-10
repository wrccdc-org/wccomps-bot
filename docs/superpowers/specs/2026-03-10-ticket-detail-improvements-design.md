# Ticket Detail Page Improvements

## Problem

The ticket detail page (`ticket_detail.html`) has several UX issues:

1. **Too much vertical scrolling** — all sections stacked linearly, empty sections take up space
2. **Cramped status bar** — badge, category, points, assignment, and actions all in one flex-wrapped line with pipe separators that break awkwardly on mobile
3. **Key metadata buried** — service name, hostname, IP address are below the fold in a fieldset
4. **Empty sections waste space** — comments and attachments show full empty states even when empty
5. **History table truncates on mobile** — details column gets cut off
6. **Resolve form wraps awkwardly** — side-by-side layout breaks on medium widths

## Approach

Collapsible sections with smart defaults, status area restructuring, and responsive fixes. Minimal template restructuring using existing `<c-fieldset collapsible>` support.

## Design

### 1. Restructured Status Area

Split the single status bar into two rows:

- **Row 1 (info):** Status badge, category (or category dropdown for assigned ops), points charged, assignment — no pipe separators, use spacing
- **Row 2 (actions):** Action buttons (Claim/Unclaim/Reopen) right-aligned

### 2. Promote Key Metadata

Move service name, hostname, and IP address out of the Ticket Information fieldset into the status area as compact inline items below the info/actions rows. These are the fields ops check first during competition.

The Ticket Information fieldset retains: description, created/resolved timestamps, resolution notes.

### 3. Collapsible Sections with Smart Defaults

Use existing `collapsible="true"` / `collapsed="true"` props:

| Section | Default State | Condition |
|---------|--------------|-----------|
| Ticket Information | Expanded | Always |
| Resolve Ticket | Expanded | Always (only shown when applicable) |
| Comments | Expanded if has comments | Collapsed if empty |
| Attachments | Expanded if has attachments | Collapsed if empty |
| History | Collapsed | Always (ops-only reference info) |

### 4. Responsive History Table

Add CSS that switches history from table to stacked cards on mobile:

```
action · actor
timestamp
details text
```

Prevents column truncation on narrow viewports.

### 5. Resolve Form Stacking

Change from side-by-side (`d-flex gap-20 flex-wrap`) to always-stacked vertical layout. Textarea gets full width, points input below. Removes awkward medium-width wrapping.

### 6. Minor Polish

- Remove pipe `|` separators from status bar (spacing handles separation)
- Reassign form uses subtle top border instead of `<hr>`

## Files to Modify

- `web/templates/ticket_detail.html` — template restructuring
- `web/static/css/app.css` — responsive history styles, status area layout
- `web/templates/ops_ticket_detail_dynamic.html` — history markup must match new responsive format
