# Scorecard Layout Redesign

**Date:** 2026-02-21
**Goal:** Reduce whitespace, improve visual hierarchy, better use of horizontal space.

## Changes

### 1. Header: Merged Neighbors as Hero

Remove the separate rank/total display. The "you" neighbor line becomes the hero element with large bold typography (~1.5em). Other neighbors display above/below at normal size. Insights stay as a bullet list below. No redundant information.

**Before:** Rank + Total (separate display) → Neighbors list → Insights
**After:** Neighbors list with "you" line as hero → Insights

### 2. Category Breakdown: Side-by-Side with Chart

Place the category table and Chart.js bar chart in a `1fr 1fr` grid inside the same module. Remove the `max-width: 600px` constraint on the chart. Chart height fills the table height naturally. Stacks on mobile.

**Before:** Table (full width) → Chart below (600px max, 200px height, dead space)
**After:** Table (left) | Chart (right), same height

### 3. Detail Sections: Stacked Full Width

Remove the 2-column `scorecard-grid`. Stack Service Uptime Detail, Red Team Detail, and Inject Detail vertically, each in its own `c-module` at full width. Eliminates the uneven column height problem (17 service rows vs 5 red team rows).

**Before:** Service (left) | Red Team (right) → Inject below
**After:** Service → Red Team → Inject (all full width, stacked)

## Files to Change

- `web/templates/scoring/scorecard.html` — template restructure
- `web/static/css/app.css` — scorecard CSS section (~30 lines of changes)

## Out of Scope

- No new data, metrics, or view changes
- No new Cotton components
- Print styles preserved (chart already hidden in print)
