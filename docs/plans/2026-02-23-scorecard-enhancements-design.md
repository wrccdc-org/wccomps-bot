# Scorecard Enhancements Design

Date: 2026-02-23

## Goals

1. **PDF Export** — Staff can generate downloadable PDF scorecards to distribute to teams
2. **Scaling Context** — Show how raw scores become scaled scores so the numbers make sense
3. **Detailed Red Team Activity** — Show per-finding detail instead of grouped summary

## Feature 1: PDF Export

### Approach: WeasyPrint

Use WeasyPrint (pure Python HTML-to-PDF) to render a print-oriented template server-side.

**Why not Playwright?** Playwright + Chromium adds ~300-400MB to the Docker image for a feature used occasionally. WeasyPrint is ~30MB with system deps and handles tables/CSS well. No chart to worry about — the scorecard doesn't render one visibly.

### Access

- Same permissions as existing scorecard: `gold_team`, `white_team`, `ticketing_admin`
- Staff generate PDFs and distribute to teams manually after competition

### Implementation

- New view `scorecard_pdf` at `/scoring/team/<num>/scorecard/pdf/`
- Renders `scorecard_print.html` — a dedicated print template with:
  - Inline CSS for WeasyPrint compatibility
  - Event name, date, team number header
  - "Generated on [date]" footer
  - All the same data as the web scorecard (including the new scaling footnote and detailed red team)
- Returns `Content-Type: application/pdf` with filename `team-NN-scorecard.pdf`
- "Download PDF" button on the web scorecard page

### Bulk Export

- "Download All Scorecards" button on the leaderboard page
- Generates a zip file containing one PDF per ranked team
- Endpoint: `/scoring/export/scorecards/`

### Docker Changes

- Add `libpango1.0-dev`, `libcairo2-dev`, `libgdk-pixbuf2.0-dev` to `Dockerfile.web`
- Add `weasyprint` to project dependencies

## Feature 2: Scaling Context

### Current State

Category breakdown table shows: Category, Points (scaled), Rank, Avg, Max. No indication of how raw scores became scaled scores.

### Design

Add a footnote below the category breakdown table showing the scaling formula for the three scaled categories:

```
Scoring weights: Service 40%, Inject 40%, Orange 20%.
Service: 8,200 raw × 1.00 = 8,200 | Inject: 6,314 raw × 1.40 = 8,839 | Orange: 4,189 raw × 1.25 = 5,236
```

- Only Service, Inject, and Orange have modifiers — Red/SLA/Recovery/Adjustments are raw values (no scaling)
- The footnote replaces the existing `text-muted` line ("Red values shown as total deductions...")
- Both lines combined under the table

### Data Requirements

The view needs to pass raw scores and modifiers to the template. The calculator already computes these internally — we just need to expose them:
- `service_raw`, `inject_raw`, `orange_raw` (pre-scaling values)
- `svc_mod`, `inj_mod`, `ora_mod` (multipliers)
- `service_weight`, `inject_weight`, `orange_weight` (from ScoringTemplate)

## Feature 3: Detailed Red Team Activity

### Current State

Red team section groups findings by `attack_vector` text with a point total per group. The `attack_vector` values contain internal shorthand (e.g., ".240 Default Creds") that isn't meaningful to teams.

### Design

Replace grouped summary with per-finding rows. Each approved finding for the team gets its own row:

| Attack Type | Target | Deduction |
|---|---|---|
| Default Credentials | web-01 (ssh) | -100 |
| Persistence | db-02 | -100 |
| **Total** | | **-1,776** |

Columns:
- **Attack Type**: `attack_type.name` (FK to AttackType) — clean, categorized name
- **Target**: `affected_boxes_display` + `affected_service` in parens if present — e.g., "web-01 (ssh)"
- **Deduction**: `points_per_team`

Each row is expandable (`<details>`) showing the outcome flags that contributed to the deduction, using the existing `outcomes_display` property:

> Root Access (-100), Credentials (-50)

### Template Changes

- Replace the current `red_scores` table (2-column: Category, Points) with a 3-column table (Attack Type, Target, Deduction)
- Add expandable `<details>` row after each finding with outcomes breakdown
- Keep the total row at the bottom

### No Model Changes Required

All needed data is already on RedTeamScore:
- `attack_type.name` for the label
- `affected_boxes_display` + `affected_service` for target
- `points_per_team` for deduction
- `outcomes_display` property for the breakdown

## Files to Change

- `web/scoring/views/leaderboard.py` — expose raw scores, modifiers, weights in scorecard context; add PDF view
- `web/templates/scoring/scorecard.html` — scaling footnote, red team detail table
- `web/templates/scoring/scorecard_print.html` — new print template for PDF
- `web/scoring/urls.py` — add PDF endpoint
- `Dockerfile.web` — add WeasyPrint system deps
- `pyproject.toml` — add weasyprint dependency
- `web/scoring/calculator.py` — refactor to expose raw scores + modifiers (or add helper function)
