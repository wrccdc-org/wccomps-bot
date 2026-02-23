# Scorecard Enhancements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add PDF export, scaling context footnote, and detailed red team findings to the scorecard.

**Architecture:** Three independent features layered onto the existing scorecard view and template. Features 2 (scaling) and 3 (red team detail) modify the web scorecard first, then Feature 1 (PDF) wraps everything in a WeasyPrint-rendered print template. Each feature has its own task with TDD.

**Tech Stack:** Django, WeasyPrint (new dep), Cotton components, existing scoring calculator.

**Design doc:** `docs/plans/2026-02-23-scorecard-enhancements-design.md`

---

### Task 1: Detailed Red Team Activity — Template + View

Replace the grouped-by-attack_vector red team summary with per-finding rows showing attack type, target boxes, deduction, and expandable outcome breakdown.

**Files:**
- Modify: `web/scoring/views/leaderboard.py:263` (scorecard view — add `select_related('attack_type')` to red_scores query)
- Modify: `web/templates/scoring/scorecard.html:229-258` (red team detail section)
- Test: `web/scoring/tests/test_event_scoring.py`

**Step 1: Write the failing test**

Add to `web/scoring/tests/test_event_scoring.py`, in a new class after `TestScorecardView`:

```python
class TestScorecardRedTeamDetail:
    """Tests for detailed red team findings on scorecard."""

    def test_scorecard_shows_attack_type(self, gold_team_user, teams, scores):
        from scoring.models import AttackType, RedTeamScore

        attack_type = AttackType.objects.create(name="Default Credentials")
        finding = RedTeamScore.objects.create(
            attack_type=attack_type,
            attack_vector=".240 Default Creds",
            points_per_team=Decimal("100"),
            is_approved=True,
        )
        finding.affected_teams.add(teams[0])

        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("scoring:scorecard", args=[1]))

        assert response.status_code == 200
        content = response.content.decode()
        assert "Default Credentials" in content  # attack_type.name shown
        assert ".240 Default Creds" not in content  # raw attack_vector NOT shown as primary label

    def test_scorecard_shows_affected_boxes(self, gold_team_user, teams, scores):
        from scoring.models import AttackType, RedTeamScore

        attack_type = AttackType.objects.create(name="RCE")
        finding = RedTeamScore.objects.create(
            attack_type=attack_type,
            affected_boxes=["web-01", "db-02"],
            affected_service="ssh",
            points_per_team=Decimal("100"),
            is_approved=True,
        )
        finding.affected_teams.add(teams[0])

        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("scoring:scorecard", args=[1]))

        content = response.content.decode()
        assert "web-01, db-02" in content
        assert "ssh" in content

    def test_scorecard_shows_outcome_flags(self, gold_team_user, teams, scores):
        from scoring.models import AttackType, RedTeamScore

        attack_type = AttackType.objects.create(name="Privilege Escalation")
        finding = RedTeamScore.objects.create(
            attack_type=attack_type,
            root_access=True,
            credentials_recovered=True,
            points_per_team=Decimal("150"),
            is_approved=True,
        )
        finding.affected_teams.add(teams[0])

        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("scoring:scorecard", args=[1]))

        content = response.content.decode()
        assert "Root Access (-100)" in content
        assert "Credentials (-50)" in content
```

**Step 2: Run tests to verify they fail**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest scoring/tests/test_event_scoring.py::TestScorecardRedTeamDetail -v`
Expected: FAIL — attack_type.name not in response, attack_vector IS in response

**Step 3: Update the scorecard view**

In `web/scoring/views/leaderboard.py:263`, add `select_related('attack_type')`:

```python
    red_scores = RedTeamScore.objects.filter(
        affected_teams=team, is_approved=True
    ).select_related("attack_type").order_by("attack_type__name", "pk")
```

Note: change ordering from `attack_vector` to `attack_type__name, pk` for cleaner grouping.

**Step 4: Update the scorecard template**

Replace lines 229-258 of `web/templates/scoring/scorecard.html` (the entire Red Team Detail `<c-module>` block) with:

```html
        <c-module>
        <h3>Red Team Detail</h3>
        {% if red_scores %}
            <c-table id="red_scores" aria_label="Red team deductions">
            <c-slot name="headers">
            <tr>
                <c-table_header sortable="false">Attack Type</c-table_header>
                <c-table_header sortable="false">Target</c-table_header>
                <c-table_header sortable="false" class="text-right">Deduction</c-table_header>
            </tr>
            </c-slot>
            {% for finding in red_scores %}
                <tr>
                    <td>{{ finding.attack_type.name|default:"Unknown" }}</td>
                    <td>
                        {% if finding.affected_boxes_display %}{{ finding.affected_boxes_display }}{% endif %}
                        {% if finding.affected_service %}({{ finding.affected_service }}){% endif %}
                    </td>
                    <td class="text-right">
                        <span class="score-negative">-{{ finding.points_per_team|floatformat:0 }}</span>
                    </td>
                </tr>
                {% if finding.outcomes_display %}
                    <tr class="feedback-row">
                        <td colspan="3">
                            <details>
                                <summary>Point breakdown</summary>
                                <p class="inject-feedback">{{ finding.outcomes_display|join:", " }}</p>
                            </details>
                        </td>
                    </tr>
                {% endif %}
            {% endfor %}
            <tr class="row-total">
                <td>
                    <strong>Total</strong>
                </td>
                <td></td>
                <td class="text-right">
                    <strong><span class="score-negative">-{{ red_total|floatformat:0 }}</span></strong>
                </td>
            </tr>
            </c-table>
        {% else %}
            <p class="text-muted">No red team deductions.</p>
        {% endif %}
        </c-module>
```

**Step 5: Run tests to verify they pass**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest scoring/tests/test_event_scoring.py::TestScorecardRedTeamDetail -v`
Expected: PASS

**Step 6: Run full test suite**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest scoring/tests/ -v`
Expected: All pass

**Step 7: Commit**

```bash
git add web/scoring/views/leaderboard.py web/templates/scoring/scorecard.html web/scoring/tests/test_event_scoring.py
git commit -m "Add per-finding red team detail to scorecard"
```

---

### Task 2: Scaling Context — Calculator + View + Template

Expose raw scores and modifiers from the calculator, pass them to the scorecard view, and display a footnote below the category table.

**Files:**
- Modify: `web/scoring/calculator.py:79-135` (add `calculate_team_score_detailed` or return raw values)
- Modify: `web/scoring/views/leaderboard.py:252-301` (pass scaling data to context)
- Modify: `web/templates/scoring/scorecard.html:185` (add footnote after category table)
- Test: `web/scoring/tests/test_event_scoring.py`

**Step 1: Write the failing test for calculator**

Add to `web/scoring/tests/test_scoring.py` (the existing formula test file), in a new class:

```python
class ScalingContextTests(TestCase):
    """Test that calculator exposes raw scores and modifiers."""

    def setUp(self) -> None:
        self.user = User.objects.create_user(username="testuser", password="test123")
        self.team = Team.objects.create(team_number=1, team_name="Test Team")
        ScoringTemplate.objects.create(
            service_weight=Decimal("40"),
            inject_weight=Decimal("40"),
            orange_weight=Decimal("20"),
            service_max=Decimal("11454"),
            inject_max=Decimal("3060"),
            orange_max=Decimal("160"),
        )
        ServiceScore.objects.create(
            team=self.team,
            service_points=Decimal("8000"),
            sla_violations=Decimal("0"),
            point_adjustments=Decimal("0"),
        )
        InjectScore.objects.create(
            team=self.team,
            inject_id="inj-1",
            inject_name="Inject 1",
            points_awarded=Decimal("2000"),
            is_approved=True,
        )

    def test_calculate_team_score_detailed_returns_raw_and_modifiers(self) -> None:
        from scoring.calculator import calculate_team_score_detailed

        result = calculate_team_score_detailed(self.team)

        assert "service_raw" in result
        assert "inject_raw" in result
        assert "orange_raw" in result
        assert "svc_modifier" in result
        assert "inj_modifier" in result
        assert "ora_modifier" in result
        assert "service_weight" in result
        assert "inject_weight" in result
        assert "orange_weight" in result
        assert result["service_raw"] == Decimal("8000")
        assert result["inject_raw"] == Decimal("2000")
```

**Step 2: Run test to verify it fails**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest scoring/tests/test_scoring.py::ScalingContextTests -v`
Expected: FAIL — `calculate_team_score_detailed` does not exist

**Step 3: Add `calculate_team_score_detailed` to calculator**

In `web/scoring/calculator.py`, add a new type alias and function. This is a thin wrapper around the existing calculation that also returns raw values and modifiers. Add after the existing `ScoreBreakdown` type alias (line 22):

```python
DetailedScoreBreakdown = dict[str, Decimal]
```

Then add a new function after `calculate_team_score` (after line 135):

```python
def calculate_team_score_detailed(team: Team) -> DetailedScoreBreakdown:
    """Like calculate_team_score but also returns raw scores, modifiers, and weights."""
    template = ScoringTemplate.objects.first() or ScoringTemplate()
    svc_mod, inj_mod, ora_mod = _get_modifiers(template)

    service_score = ServiceScore.objects.filter(team=team).first()
    if service_score:
        service_raw = service_score.service_points
        sla_raw = service_score.sla_violations
        point_adj = service_score.point_adjustments
    else:
        service_raw = Decimal("0")
        sla_raw = Decimal("0")
        point_adj = Decimal("0")

    inject_raw = get_approved_inject_total(team)
    orange_raw = get_approved_orange_total(team)
    red_raw = get_approved_red_deductions(team)
    recovery_raw = IncidentReport.objects.filter(
        team=team,
        gold_team_reviewed=True,
    ).aggregate(total=Sum("points_returned"))["total"] or Decimal("0")

    scaled_service = (service_raw * svc_mod).quantize(Decimal("1"))
    scaled_inject = (inject_raw * inj_mod).quantize(Decimal("1"))
    scaled_orange = (orange_raw * ora_mod).quantize(Decimal("1"))

    total_score = scaled_service + scaled_inject + scaled_orange + sla_raw + point_adj + red_raw + recovery_raw

    return {
        # Standard fields (same as calculate_team_score)
        "service_points": scaled_service,
        "inject_points": scaled_inject,
        "orange_points": scaled_orange,
        "red_deductions": red_raw,
        "sla_penalties": sla_raw,
        "point_adjustments": point_adj,
        "incident_recovery_points": recovery_raw,
        "total_score": total_score,
        # Raw scores (before scaling)
        "service_raw": service_raw,
        "inject_raw": inject_raw,
        "orange_raw": orange_raw,
        # Modifiers
        "svc_modifier": svc_mod,
        "inj_modifier": inj_mod,
        "ora_modifier": ora_mod,
        # Weights
        "service_weight": template.service_weight,
        "inject_weight": template.inject_weight,
        "orange_weight": template.orange_weight,
    }
```

**Step 4: Run test to verify it passes**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest scoring/tests/test_scoring.py::ScalingContextTests -v`
Expected: PASS

**Step 5: Write the failing test for scorecard view showing scaling footnote**

Add to `web/scoring/tests/test_event_scoring.py`:

```python
class TestScorecardScalingContext:
    """Tests for scaling context footnote on scorecard."""

    def test_scorecard_shows_scaling_weights(self, gold_team_user, teams, scores):
        from scoring.models import ScoringTemplate

        ScoringTemplate.objects.create(
            service_weight=Decimal("40"),
            inject_weight=Decimal("40"),
            orange_weight=Decimal("20"),
            service_max=Decimal("11454"),
            inject_max=Decimal("3060"),
            orange_max=Decimal("160"),
        )

        client = Client()
        client.force_login(gold_team_user)
        response = client.get(reverse("scoring:scorecard", args=[1]))

        content = response.content.decode()
        assert "Service 40%" in content
        assert "Inject 40%" in content
        assert "Orange 20%" in content
```

**Step 6: Run test to verify it fails**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest scoring/tests/test_event_scoring.py::TestScorecardScalingContext -v`
Expected: FAIL — weights not in response

**Step 7: Update the scorecard view to pass scaling data**

In `web/scoring/views/leaderboard.py`, import the new function:

```python
from ..calculator import calculate_team_score_detailed, get_leaderboard
```

Then in the `scorecard` view (around line 260), after getting the `score` and `team`, add:

```python
    detailed = calculate_team_score_detailed(team)
```

And add to the context dict:

```python
        "scaling": {
            "service_raw": detailed["service_raw"],
            "inject_raw": detailed["inject_raw"],
            "orange_raw": detailed["orange_raw"],
            "svc_modifier": detailed["svc_modifier"],
            "inj_modifier": detailed["inj_modifier"],
            "ora_modifier": detailed["ora_modifier"],
            "service_weight": detailed["service_weight"],
            "inject_weight": detailed["inject_weight"],
            "orange_weight": detailed["orange_weight"],
        },
```

**Step 8: Update the template footnote**

Replace line 185 of `web/templates/scoring/scorecard.html`:

```html
                <p class="text-muted text-xs">Red values shown as total deductions (lower is better).</p>
```

With:

```html
                <p class="text-muted text-xs">Red values shown as total deductions (lower is better).</p>
                {% if scaling %}
                    <p class="text-muted text-xs">
                        Scoring weights: Service {{ scaling.service_weight|floatformat:0 }}%, Inject {{ scaling.inject_weight|floatformat:0 }}%, Orange {{ scaling.orange_weight|floatformat:0 }}%.<br>
                        Service: {{ scaling.service_raw|floatformat:0 }} raw &times; {{ scaling.svc_modifier|floatformat:2 }}
                        | Inject: {{ scaling.inject_raw|floatformat:0 }} raw &times; {{ scaling.inj_modifier|floatformat:2 }}
                        | Orange: {{ scaling.orange_raw|floatformat:0 }} raw &times; {{ scaling.ora_modifier|floatformat:2 }}
                    </p>
                {% endif %}
```

**Step 9: Run tests to verify they pass**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest scoring/tests/test_event_scoring.py::TestScorecardScalingContext scoring/tests/test_scoring.py::ScalingContextTests -v`
Expected: PASS

**Step 10: Run full test suite**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest scoring/tests/ -v`
Expected: All pass

**Step 11: Commit**

```bash
git add web/scoring/calculator.py web/scoring/views/leaderboard.py web/templates/scoring/scorecard.html web/scoring/tests/test_scoring.py web/scoring/tests/test_event_scoring.py
git commit -m "Add scaling context footnote to scorecard"
```

---

### Task 3: PDF Export — Dependencies + View + Template

Add WeasyPrint, create a print template, and add single-team + bulk PDF export endpoints.

**Files:**
- Modify: `pyproject.toml:6-29` (add weasyprint dependency)
- Modify: `Dockerfile.web:6-10` (add system deps for WeasyPrint)
- Create: `web/templates/scoring/scorecard_print.html`
- Modify: `web/scoring/views/leaderboard.py` (add `scorecard_pdf` view)
- Modify: `web/scoring/views/export.py` (add `export_scorecards` bulk view)
- Modify: `web/scoring/views/__init__.py` (export new views)
- Modify: `web/scoring/urls.py` (add PDF routes)
- Modify: `web/templates/scoring/scorecard.html` (add "Download PDF" button)
- Modify: `web/templates/scoring/leaderboard.html` (add "Download All Scorecards" button)
- Test: `web/scoring/tests/test_event_scoring.py`

**Step 1: Add WeasyPrint dependency**

In `pyproject.toml`, add to `dependencies` list (after the `openpyxl` line):

```toml
    "weasyprint>=63.0",
```

In `Dockerfile.web`, replace the apt-get install block (lines 6-10):

```dockerfile
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libcairo2 \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*
```

Run: `uv lock && uv sync`

**Step 2: Add mypy override for weasyprint**

WeasyPrint doesn't ship type stubs. Add to `pyproject.toml` after the existing mypy overrides:

```toml
[[tool.mypy.overrides]]
module = "weasyprint"
ignore_missing_imports = true
```

**Step 3: Write the failing test for single PDF**

Add to `web/scoring/tests/test_event_scoring.py`:

```python
class TestScorecardPdf:
    """Tests for PDF scorecard export."""

    def test_pdf_returns_pdf_content_type(self, gold_team_user, teams, scores):
        client = Client()
        client.force_login(gold_team_user)
        url = reverse("scoring:scorecard_pdf", args=[1])
        response = client.get(url)

        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert 'filename="team-01-scorecard.pdf"' in response["Content-Disposition"]

    def test_pdf_requires_gold_team(self, client, teams, scores):
        url = reverse("scoring:scorecard_pdf", args=[1])
        response = client.get(url)
        assert response.status_code == 302

    def test_pdf_returns_404_for_missing_team(self, gold_team_user, teams, scores):
        client = Client()
        client.force_login(gold_team_user)
        url = reverse("scoring:scorecard_pdf", args=[99])
        response = client.get(url)
        assert response.status_code == 404
```

**Step 4: Run test to verify it fails**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest scoring/tests/test_event_scoring.py::TestScorecardPdf -v`
Expected: FAIL — URL not found (NoReverseMatch)

**Step 5: Create the print template**

Create `web/templates/scoring/scorecard_print.html`:

```html
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Team {{ team.team_number|stringformat:"02d" }} Scorecard</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 11px;
            color: #1a1a1a;
            margin: 20px 30px;
            line-height: 1.4;
        }
        h1 { font-size: 20px; margin: 0 0 5px 0; }
        h2 { font-size: 14px; margin: 15px 0 8px 0; border-bottom: 1px solid #ccc; padding-bottom: 3px; }
        .header { margin-bottom: 15px; }
        .header .subtitle { color: #666; font-size: 12px; }
        .rank-hero {
            font-size: 16px;
            font-weight: bold;
            margin: 10px 0;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 10px;
            font-size: 11px;
        }
        th, td {
            padding: 4px 8px;
            text-align: left;
            border-bottom: 1px solid #e0e0e0;
        }
        th { background: #f5f5f5; font-weight: 600; }
        .text-right { text-align: right; }
        .row-total td { border-top: 2px solid #999; font-weight: bold; }
        .score-negative { color: #c0392b; }
        .score-positive { color: #27ae60; }
        .row-below-avg td { background: #fff5f5; }
        .footnote { color: #666; font-size: 10px; margin: 5px 0 15px 0; }
        .outcomes { color: #666; font-size: 10px; padding-left: 16px; }
        .footer {
            margin-top: 20px;
            padding-top: 10px;
            border-top: 1px solid #ccc;
            color: #999;
            font-size: 9px;
        }
        .insights { margin: 5px 0; padding-left: 20px; }
        .insights li { margin-bottom: 2px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Team {{ team.team_number|stringformat:"02d" }} Scorecard</h1>
        {% if event %}<div class="subtitle">{{ event.name }}</div>{% endif %}
    </div>

    <div class="rank-hero">
        {% if score.rank %}#{{ score.rank }} of {{ stats.team_count }} teams &mdash; {% endif %}{{ score.total_score|floatformat:0 }} points
    </div>

    {% if stats.insights %}
        <ul class="insights">
            {% for insight in stats.insights %}<li>{{ insight }}</li>{% endfor %}
        </ul>
    {% endif %}

    <h2>Category Breakdown</h2>
    <table>
        <thead>
            <tr>
                <th>Category</th>
                <th class="text-right">Points</th>
                <th class="text-right">Rank</th>
                <th class="text-right">Avg</th>
                <th class="text-right">Max</th>
            </tr>
        </thead>
        <tbody>
            {% with svc_rank=stats.category_ranks.services %}
                <tr>
                    <td>Service (scaled)</td>
                    <td class="text-right">{{ score.service_points|floatformat:0 }}</td>
                    {% if svc_rank %}
                        <td class="text-right">#{{ svc_rank.rank }} of {{ stats.team_count }}</td>
                        <td class="text-right">{{ svc_rank.avg|floatformat:0 }}</td>
                        <td class="text-right">{{ svc_rank.max|floatformat:0 }}</td>
                    {% else %}
                        <td class="text-right">&mdash;</td>
                        <td class="text-right">&mdash;</td>
                        <td class="text-right">&mdash;</td>
                    {% endif %}
                </tr>
            {% endwith %}
            {% with inj_rank=stats.category_ranks.injects %}
                <tr>
                    <td>Injects (scaled)</td>
                    <td class="text-right">{{ score.inject_points|floatformat:0 }}</td>
                    {% if inj_rank %}
                        <td class="text-right">#{{ inj_rank.rank }} of {{ stats.team_count }}</td>
                        <td class="text-right">{{ inj_rank.avg|floatformat:0 }}</td>
                        <td class="text-right">{{ inj_rank.max|floatformat:0 }}</td>
                    {% else %}
                        <td class="text-right">&mdash;</td>
                        <td class="text-right">&mdash;</td>
                        <td class="text-right">&mdash;</td>
                    {% endif %}
                </tr>
            {% endwith %}
            {% with ora_rank=stats.category_ranks.orange %}
                <tr>
                    <td>Orange (scaled)</td>
                    <td class="text-right">{{ score.orange_points|floatformat:0 }}</td>
                    {% if ora_rank %}
                        <td class="text-right">#{{ ora_rank.rank }} of {{ stats.team_count }}</td>
                        <td class="text-right">{{ ora_rank.avg|floatformat:0 }}</td>
                        <td class="text-right">{{ ora_rank.max|floatformat:0 }}</td>
                    {% else %}
                        <td class="text-right">&mdash;</td>
                        <td class="text-right">&mdash;</td>
                        <td class="text-right">&mdash;</td>
                    {% endif %}
                </tr>
            {% endwith %}
            {% with red_rank=stats.category_ranks.red %}
                <tr>
                    <td>Red Team</td>
                    <td class="text-right"><span class="score-negative">{{ score.red_deductions|floatformat:0 }}</span></td>
                    {% if red_rank %}
                        <td class="text-right">#{{ red_rank.rank }} of {{ stats.team_count }}</td>
                        <td class="text-right">{{ red_rank.avg|floatformat:0 }}</td>
                        <td class="text-right">{{ red_rank.max|floatformat:0 }}</td>
                    {% else %}
                        <td class="text-right">&mdash;</td>
                        <td class="text-right">&mdash;</td>
                        <td class="text-right">&mdash;</td>
                    {% endif %}
                </tr>
            {% endwith %}
            {% if score.sla_penalties %}
                {% with sla_rank=stats.category_ranks.sla %}
                    <tr>
                        <td>SLA Violations</td>
                        <td class="text-right"><span class="score-negative">{{ score.sla_penalties|floatformat:0 }}</span></td>
                        {% if sla_rank %}
                            <td class="text-right">#{{ sla_rank.rank }} of {{ stats.team_count }}</td>
                            <td class="text-right">{{ sla_rank.avg|floatformat:0 }}</td>
                            <td class="text-right">{{ sla_rank.max|floatformat:0 }}</td>
                        {% else %}
                            <td class="text-right">&mdash;</td>
                            <td class="text-right">&mdash;</td>
                            <td class="text-right">&mdash;</td>
                        {% endif %}
                    </tr>
                {% endwith %}
            {% endif %}
            {% if score.incident_recovery_points %}
                {% with rec_rank=stats.category_ranks.recovery %}
                    <tr>
                        <td>Incident Recovery</td>
                        <td class="text-right"><span class="score-positive">+{{ score.incident_recovery_points|floatformat:0 }}</span></td>
                        {% if rec_rank %}
                            <td class="text-right">#{{ rec_rank.rank }} of {{ stats.team_count }}</td>
                            <td class="text-right">{{ rec_rank.avg|floatformat:0 }}</td>
                            <td class="text-right">{{ rec_rank.max|floatformat:0 }}</td>
                        {% else %}
                            <td class="text-right">&mdash;</td>
                            <td class="text-right">&mdash;</td>
                            <td class="text-right">&mdash;</td>
                        {% endif %}
                    </tr>
                {% endwith %}
            {% endif %}
            {% if score.point_adjustments %}
                {% with adj_rank=stats.category_ranks.adjustments %}
                    <tr>
                        <td>Point Adjustments</td>
                        <td class="text-right">{{ score.point_adjustments|floatformat:0 }}</td>
                        {% if adj_rank %}
                            <td class="text-right">#{{ adj_rank.rank }} of {{ stats.team_count }}</td>
                            <td class="text-right">{{ adj_rank.avg|floatformat:0 }}</td>
                            <td class="text-right">{{ adj_rank.max|floatformat:0 }}</td>
                        {% else %}
                            <td class="text-right">&mdash;</td>
                            <td class="text-right">&mdash;</td>
                            <td class="text-right">&mdash;</td>
                        {% endif %}
                    </tr>
                {% endwith %}
            {% endif %}
            <tr class="row-total">
                <td>Grand Total</td>
                <td class="text-right">{{ score.total_score|floatformat:0 }}</td>
                <td></td><td></td><td></td>
            </tr>
        </tbody>
    </table>
    <p class="footnote">
        Red values shown as total deductions (lower is better).
        {% if scaling %}
            <br>Scoring weights: Service {{ scaling.service_weight|floatformat:0 }}%, Inject {{ scaling.inject_weight|floatformat:0 }}%, Orange {{ scaling.orange_weight|floatformat:0 }}%.
            Service: {{ scaling.service_raw|floatformat:0 }} raw &times; {{ scaling.svc_modifier|floatformat:2 }}
            | Inject: {{ scaling.inject_raw|floatformat:0 }} raw &times; {{ scaling.inj_modifier|floatformat:2 }}
            | Orange: {{ scaling.orange_raw|floatformat:0 }} raw &times; {{ scaling.ora_modifier|floatformat:2 }}
        {% endif %}
    </p>

    {% if stats.service_stats %}
        <h2>Service Uptime Detail</h2>
        <table>
            <thead>
                <tr>
                    <th>Service</th>
                    <th class="text-right">Points</th>
                    <th class="text-right">vs Avg</th>
                    <th class="text-right">Rank</th>
                </tr>
            </thead>
            <tbody>
                {% for svc in stats.service_stats %}
                    <tr {% if svc.below_avg %}class="row-below-avg"{% endif %}>
                        <td>{{ svc.name }}</td>
                        <td class="text-right">{{ svc.points|floatformat:0 }}</td>
                        <td class="text-right">
                            {% if svc.delta > 0 %}<span class="score-positive">+{{ svc.delta }}</span>{% elif svc.delta < 0 %}<span class="score-negative">{{ svc.delta }}</span>{% else %}0{% endif %}
                        </td>
                        <td class="text-right">#{{ svc.rank }}</td>
                    </tr>
                {% endfor %}
                <tr class="row-total">
                    <td>Total</td>
                    <td class="text-right">{{ service_total|floatformat:0 }}</td>
                    <td></td><td></td>
                </tr>
            </tbody>
        </table>
    {% endif %}

    <h2>Red Team Detail</h2>
    {% if red_scores %}
        <table>
            <thead>
                <tr>
                    <th>Attack Type</th>
                    <th>Target</th>
                    <th class="text-right">Deduction</th>
                </tr>
            </thead>
            <tbody>
                {% for finding in red_scores %}
                    <tr>
                        <td>{{ finding.attack_type.name|default:"Unknown" }}</td>
                        <td>
                            {% if finding.affected_boxes_display %}{{ finding.affected_boxes_display }}{% endif %}
                            {% if finding.affected_service %}({{ finding.affected_service }}){% endif %}
                        </td>
                        <td class="text-right"><span class="score-negative">-{{ finding.points_per_team|floatformat:0 }}</span></td>
                    </tr>
                    {% if finding.outcomes_display %}
                        <tr>
                            <td colspan="3" class="outcomes">{{ finding.outcomes_display|join:", " }}</td>
                        </tr>
                    {% endif %}
                {% endfor %}
                <tr class="row-total">
                    <td>Total</td>
                    <td></td>
                    <td class="text-right"><span class="score-negative">-{{ red_total|floatformat:0 }}</span></td>
                </tr>
            </tbody>
        </table>
    {% else %}
        <p>No red team deductions.</p>
    {% endif %}

    {% if stats.inject_stats %}
        <h2>Inject Detail</h2>
        <table>
            <thead>
                <tr>
                    <th>Inject</th>
                    <th class="text-right">Points</th>
                    <th class="text-right">vs Avg</th>
                    <th class="text-right">Rank</th>
                </tr>
            </thead>
            <tbody>
                {% for inj in stats.inject_stats %}
                    <tr {% if inj.below_avg %}class="row-below-avg"{% endif %}>
                        <td>{{ inj.name }}</td>
                        <td class="text-right">{{ inj.points|floatformat:0 }}</td>
                        <td class="text-right">
                            {% if inj.delta > 0 %}<span class="score-positive">+{{ inj.delta }}</span>{% elif inj.delta < 0 %}<span class="score-negative">{{ inj.delta }}</span>{% else %}0{% endif %}
                        </td>
                        <td class="text-right">#{{ inj.rank }}</td>
                    </tr>
                    {% if inj.feedback %}
                        <tr>
                            <td colspan="4" class="outcomes"><em>{{ inj.feedback }}</em></td>
                        </tr>
                    {% endif %}
                {% endfor %}
                <tr class="row-total">
                    <td>Total</td>
                    <td class="text-right">{{ inject_total|floatformat:0 }}</td>
                    <td></td><td></td>
                </tr>
            </tbody>
        </table>
    {% endif %}

    <div class="footer">
        Generated on {% now "Y-m-d H:i" %} | WCComps Scoring System
    </div>
</body>
</html>
```

**Step 6: Add the `scorecard_pdf` view**

In `web/scoring/views/leaderboard.py`, add at the top with other imports:

```python
import weasyprint
from django.template.loader import render_to_string
```

Then add after the existing `scorecard` view:

```python
@require_permission(
    "gold_team",
    "white_team",
    "ticketing_admin",
    error_message="Only authorized staff can export scorecards",
)
def scorecard_pdf(request: HttpRequest, team_number: int) -> HttpResponse:
    """Generate PDF scorecard for a single team."""
    score = get_object_or_404(FinalScore, team__team_number=team_number)
    team = score.team

    red_scores = RedTeamScore.objects.filter(
        affected_teams=team, is_approved=True
    ).select_related("attack_type").order_by("attack_type__name", "pk")

    stats = _compute_scorecard_stats(team, score)
    detailed = calculate_team_score_detailed(team)

    red_total = sum(r.points_per_team for r in red_scores)
    inject_total = sum(i["points"] for i in stats["inject_stats"])
    service_total = sum(s["points"] for s in stats["service_stats"])

    context = {
        "team": team,
        "score": score,
        "red_scores": red_scores,
        "stats": stats,
        "red_total": red_total,
        "inject_total": inject_total,
        "service_total": service_total,
        "scaling": {
            "service_raw": detailed["service_raw"],
            "inject_raw": detailed["inject_raw"],
            "orange_raw": detailed["orange_raw"],
            "svc_modifier": detailed["svc_modifier"],
            "inj_modifier": detailed["inj_modifier"],
            "ora_modifier": detailed["ora_modifier"],
            "service_weight": detailed["service_weight"],
            "inject_weight": detailed["inject_weight"],
            "orange_weight": detailed["orange_weight"],
        },
    }

    html_string = render_to_string("scoring/scorecard_print.html", context, request=request)
    pdf_bytes = weasyprint.HTML(string=html_string).write_pdf()

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="team-{team_number:02d}-scorecard.pdf"'
    return response
```

**Step 7: Add the bulk export view**

In `web/scoring/views/export.py`, add at the end:

```python
@require_permission("gold_team", error_message="Only Gold Team members can access this")
def export_scorecards(request: HttpRequest) -> HttpResponse:
    """Export all team scorecards as a zip of PDFs."""
    import io
    import zipfile
    from datetime import datetime

    import weasyprint
    from django.template.loader import render_to_string
    from django.utils import timezone

    from ..calculator import calculate_team_score_detailed
    from ..models import FinalScore, RedTeamScore
    from .leaderboard import _compute_scorecard_stats

    scores = FinalScore.objects.filter(
        is_excluded=False, rank__isnull=False
    ).select_related("team").order_by("rank")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for final_score in scores:
            team = final_score.team
            red_scores = RedTeamScore.objects.filter(
                affected_teams=team, is_approved=True
            ).select_related("attack_type").order_by("attack_type__name", "pk")

            stats = _compute_scorecard_stats(team, final_score)
            detailed = calculate_team_score_detailed(team)

            context = {
                "team": team,
                "score": final_score,
                "red_scores": red_scores,
                "stats": stats,
                "red_total": sum(r.points_per_team for r in red_scores),
                "inject_total": sum(i["points"] for i in stats["inject_stats"]),
                "service_total": sum(s["points"] for s in stats["service_stats"]),
                "scaling": {
                    "service_raw": detailed["service_raw"],
                    "inject_raw": detailed["inject_raw"],
                    "orange_raw": detailed["orange_raw"],
                    "svc_modifier": detailed["svc_modifier"],
                    "inj_modifier": detailed["inj_modifier"],
                    "ora_modifier": detailed["ora_modifier"],
                    "service_weight": detailed["service_weight"],
                    "inject_weight": detailed["inject_weight"],
                    "orange_weight": detailed["orange_weight"],
                },
            }

            html_string = render_to_string("scoring/scorecard_print.html", context, request=request)
            pdf_bytes = weasyprint.HTML(string=html_string).write_pdf()
            zf.writestr(f"team-{team.team_number:02d}-scorecard.pdf", pdf_bytes)

    timestamp = timezone.now().strftime("%Y%m%d-%H%M%S")
    response = HttpResponse(buf.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="scorecards-{timestamp}.zip"'
    return response
```

**Step 8: Wire up URLs and exports**

In `web/scoring/urls.py`, add after line 12:

```python
    path("team/<int:team_number>/scorecard/pdf/", views.scorecard_pdf, name="scorecard_pdf"),
```

Add after line 76 (before the closing `]`):

```python
    path("export/scorecards/", views.export_scorecards, name="export_scorecards"),
```

In `web/scoring/views/__init__.py`, add `scorecard_pdf` to the leaderboard imports:

```python
from .leaderboard import (
    _CategoryRank,
    _compute_scorecard_stats,
    _InjectStat,
    _Neighbor,
    _ScorecardStats,
    _ServiceStat,
    leaderboard,
    scorecard,
    scorecard_pdf,
)
```

And `export_scorecards` to the export imports:

```python
from .export import (
    export_all,
    export_final_scores,
    export_incidents,
    export_index,
    export_inject_grades,
    export_orange_adjustments,
    export_red_scores,
    export_scorecards,
)
```

And add both to the `__all__` list.

**Step 9: Add buttons to templates**

In `web/templates/scoring/scorecard.html`, add a "Download PDF" link in the page header area. After line 8 (`<c-page_header>`) add:

```html
        <c-slot name="toolbar">
            <c-link href="{% url 'scoring:scorecard_pdf' team.team_number %}">Download PDF</c-link>
        </c-slot>
```

Wait — the `c-page_header` is a self-closing tag on line 8. We need to check if it supports slots. Looking at the template, the leaderboard uses `c-module` with `c-slot name="toolbar"`. Let's add the PDF link as a simple link below the page header instead:

After the `<c-page_header>` line, before `<c-module>` on line 9:

```html
        <div class="mb-10">
            <c-link href="{% url 'scoring:scorecard_pdf' team.team_number %}">Download PDF</c-link>
        </div>
```

In `web/templates/scoring/leaderboard.html`, add to the toolbar slot (line 11):

```html
    <c-link href="{% url 'scoring:export_scorecards' %}">Download All PDFs</c-link>
```

**Step 10: Run tests to verify they pass**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest scoring/tests/test_event_scoring.py::TestScorecardPdf -v`
Expected: PASS

**Step 11: Run full test suite**

Run: `cd web && DB_HOST=localhost DB_PORT=5433 DB_USER=test_user DB_PASSWORD=test_password DB_NAME=wccomps_test uv run pytest scoring/tests/ -v`
Expected: All pass

**Step 12: Run linting and type checks**

Run: `cd web && uv run ruff format . && uv run ruff check . && uv run mypy`
Expected: Clean

**Step 13: Commit**

```bash
git add pyproject.toml uv.lock Dockerfile.web web/scoring/views/leaderboard.py web/scoring/views/export.py web/scoring/views/__init__.py web/scoring/urls.py web/templates/scoring/scorecard.html web/templates/scoring/scorecard_print.html web/templates/scoring/leaderboard.html web/scoring/tests/test_event_scoring.py
git commit -m "Add PDF scorecard export (single + bulk)"
```

---

### Task 4: Final Verification

**Step 1: Run the full deploy checks**

Run: `./deploy.sh` (this runs ruff, djlint, mypy, migrations, and tests)
Expected: All pass, deploys successfully

**Step 2: Verify on production**

- Visit `/scoring/team/15/scorecard/` and confirm:
  - Red team detail shows per-finding rows with attack type, target, deduction, expandable outcomes
  - Scaling footnote appears below category table with weights and raw×modifier
  - "Download PDF" link is present
- Click "Download PDF" and verify the PDF renders correctly
- Visit `/scoring/` leaderboard and click "Download All PDFs" — verify zip contains one PDF per team
