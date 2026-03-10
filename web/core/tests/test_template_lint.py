"""Template linting tests to enforce best practices."""

import re
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"
STATIC_DIR = Path(__file__).parent.parent.parent / "static"


def get_all_template_files() -> list[Path]:
    """Get all Django template files."""
    return list(TEMPLATES_DIR.rglob("*.html"))


def has_cotton_components(content: str) -> bool:
    """Check if template uses cotton components (<c-... or c-...)."""
    return bool(re.search(r"<c-\w+|{%\s*c-\w+", content))


def has_cotton_load(content: str) -> bool:
    """Check if template has {% load cotton %} or {% load ... cotton ... %} statement."""
    # Match {% load cotton %} or {% load static cotton %} etc.
    return bool(re.search(r"{%\s*load\s+[^%]*\bcotton\b[^%]*%}", content))


def is_cotton_component(path: Path) -> bool:
    """Check if template is a cotton component definition."""
    return "cotton" in path.parts


def is_email_template(path: Path) -> bool:
    """Check if template is an email template (allowed to have inline styles)."""
    return "emails" in path.parts


def is_pdf_template(path: Path) -> bool:
    """Check if template is a PDF template (allowed to have inline styles)."""
    return "pdf" in path.name.lower() or "scorecard" in path.name.lower()


def extends_django_admin_base(path: Path) -> bool:
    """Check if template extends Django's admin base (not our custom base with Cotton)."""
    content = path.read_text()
    # These templates extend Django's admin base, not our custom base
    return bool(re.search(r'{%\s*extends\s+["\']admin/base_site\.html["\']', content))


class TestCottonImports:
    """Tests for cotton template tag imports."""

    def test_cotton_components_have_load_statement(self) -> None:
        """All templates using cotton components must have {% load cotton %}."""
        templates_missing_load = []

        for template_path in get_all_template_files():
            # Skip cotton component definitions - they don't need {% load cotton %}
            if is_cotton_component(template_path):
                continue

            content = template_path.read_text()

            if has_cotton_components(content) and not has_cotton_load(content):
                relative_path = template_path.relative_to(TEMPLATES_DIR)
                templates_missing_load.append(str(relative_path))

        if templates_missing_load:
            pytest.fail(
                "Templates using cotton components without {% load cotton %}:\n"
                + "\n".join(f"  - {t}" for t in sorted(templates_missing_load))
            )


class TestInlineStyles:
    """Tests for inline style usage (should use CSS classes instead)."""

    # Patterns that indicate inline style usage
    INLINE_STYLE_PATTERNS = [
        (r'style="[^"]*display:\s*(none|block|flex)', "inline display style"),
        (r"\.style\.display\s*=", "JavaScript .style.display manipulation"),
    ]

    def test_no_inline_display_styles_in_html(self) -> None:
        """Templates should use CSS classes instead of inline display styles."""
        templates_with_issues: list[tuple[str, str, int]] = []

        for template_path in get_all_template_files():
            # Skip email, PDF, and cotton component templates
            if is_email_template(template_path) or is_pdf_template(template_path) or is_cotton_component(template_path):
                continue

            content = template_path.read_text()
            relative_path = template_path.relative_to(TEMPLATES_DIR)

            for pattern, description in self.INLINE_STYLE_PATTERNS:
                for match in re.finditer(pattern, content):
                    # Find line number
                    line_num = content[: match.start()].count("\n") + 1
                    templates_with_issues.append((str(relative_path), description, line_num))

        if templates_with_issues:
            issue_lines = [f"  - {path}:{line} ({desc})" for path, desc, line in sorted(templates_with_issues)]
            pytest.fail("Templates using inline styles (use CSS classes instead):\n" + "\n".join(issue_lines))


class TestTemplateBlockNames:
    """Tests to ensure templates use correct block names for their base templates."""

    # Map of base template patterns to expected content block names
    BASE_TEMPLATE_BLOCKS = {
        "scoring/red_base.html": "red_content",
        "scoring/orange_base.html": "orange_content",
        "scoring/base.html": "scoring_content",
        "admin/base.html": "admin_content",
        "registration/admin_base.html": "registration_content",
    }

    # Templates that override standard Django blocks (not our custom content blocks)
    EXCLUDED_TEMPLATES = {
        "admin/base_site.html",  # Django admin override, uses standard admin blocks
    }

    def test_block_names_match_base_templates(self) -> None:
        """Templates must use the correct block name for their base template."""
        mismatches: list[tuple[str, str, str]] = []

        for template_path in get_all_template_files():
            content = template_path.read_text()
            relative_path = template_path.relative_to(TEMPLATES_DIR)

            # Skip excluded templates
            if str(relative_path) in self.EXCLUDED_TEMPLATES:
                continue

            # Find what base template this extends
            extends_match = re.search(r'{%\s*extends\s+["\']([^"\']+)["\']', content)
            if not extends_match:
                continue

            base_template = extends_match.group(1)

            # Check if this base template has a required block name
            for base_pattern, expected_block in self.BASE_TEMPLATE_BLOCKS.items():
                if base_pattern in base_template:
                    # Find all block declarations (excluding title)
                    blocks = re.findall(r"{%\s*block\s+(\w+)", content)
                    content_blocks = [b for b in blocks if b != "title"]

                    if content_blocks and expected_block not in content_blocks:
                        mismatches.append((str(relative_path), expected_block, content_blocks[0]))
                    break

        if mismatches:
            issue_lines = [
                f"  - {path}: expected '{expected}', found '{actual}'" for path, expected, actual in sorted(mismatches)
            ]
            pytest.fail("Templates using wrong block name for their base:\n" + "\n".join(issue_lines))


class TestCottonComponentUsage:
    """Tests to ensure Cotton components are used instead of raw HTML patterns."""

    RAW_HTML_PATTERNS = [
        # Badges - should use <c-badge>
        # Matches: <span class="badge ..."> but not inside Alpine templates
        (
            r'<span[^>]*class="[^"]*\bbadge\b[^"]*"[^>]*>',
            "raw badge span",
            "<c-badge>",
        ),
        # Stats cards - should use <c-stats_card>
        (
            r'<div[^>]*class="[^"]*\bstats-card\b[^"]*"[^>]*>',
            "raw stats-card div",
            "<c-stats_card>",
        ),
        # Empty state - should use <c-empty_state>
        (
            r'<div[^>]*class="[^"]*\bempty-state\b[^"]*"[^>]*>',
            "raw empty-state div",
            "<c-empty_state>",
        ),
    ]

    # Patterns that indicate incorrect component usage
    INVALID_COMPONENT_PATTERNS = [
        # c-button with href - should use c-link instead
        (
            r"<c-button[^>]*\bhref=",
            "c-button with href (buttons don't navigate)",
            "<c-link>",
        ),
    ]

    def test_no_invalid_component_usage(self) -> None:
        """Components should be used correctly (e.g., no href on c-button)."""
        templates_with_issues: list[tuple[str, str, int, str]] = []

        for template_path in get_all_template_files():
            if is_cotton_component(template_path):
                continue

            content = template_path.read_text()
            relative_path = template_path.relative_to(TEMPLATES_DIR)

            for pattern, description, suggestion in self.INVALID_COMPONENT_PATTERNS:
                for match in re.finditer(pattern, content, re.IGNORECASE):
                    line_num = content[: match.start()].count("\n") + 1
                    templates_with_issues.append((str(relative_path), description, line_num, suggestion))

        if templates_with_issues:
            issue_lines = [
                f"  - {path}:{line} {desc} -> use {sug}" for path, desc, line, sug in sorted(templates_with_issues)
            ]
            pytest.fail("Templates with invalid component usage:\n" + "\n".join(issue_lines))

    def test_no_raw_html_patterns(self) -> None:
        """Templates should use Cotton components instead of raw HTML patterns."""
        templates_with_issues: list[tuple[str, str, int, str]] = []

        for template_path in get_all_template_files():
            # Skip cotton component definitions (they define the components)
            if is_cotton_component(template_path):
                continue
            # Skip email templates
            if is_email_template(template_path):
                continue
            # Skip PDF templates
            if is_pdf_template(template_path):
                continue
            # Skip templates extending Django admin base (don't use Cotton)
            if extends_django_admin_base(template_path):
                continue

            content = template_path.read_text()
            relative_path = template_path.relative_to(TEMPLATES_DIR)

            for pattern, description, suggestion in self.RAW_HTML_PATTERNS:
                for match in re.finditer(pattern, content, re.IGNORECASE | re.DOTALL):
                    line_num = content[: match.start()].count("\n") + 1
                    templates_with_issues.append((str(relative_path), description, line_num, suggestion))

        if templates_with_issues:
            issue_lines = [
                f"  - {path}:{line} {desc} -> use {sug}" for path, desc, line, sug in sorted(templates_with_issues)
            ]
            pytest.fail("Templates using raw HTML instead of Cotton components:\n" + "\n".join(issue_lines))


class TestDetailGridUsage:
    """Tests to ensure c-detail_grid uses c-detail_row instead of raw <dt>/<dd>."""

    def test_no_raw_dt_in_detail_grid(self) -> None:
        """c-detail_grid contents should use c-detail_row, not raw <dt>/<dd>."""
        templates_with_issues: list[tuple[str, int]] = []

        for template_path in get_all_template_files():
            if is_cotton_component(template_path):
                continue

            content = template_path.read_text()
            relative_path = template_path.relative_to(TEMPLATES_DIR)

            # Find all c-detail_grid blocks and check for raw <dt> inside them
            for grid_match in re.finditer(
                r"<c-detail_grid[^>]*>(.*?)</c-detail_grid>",
                content,
                re.DOTALL,
            ):
                grid_content = grid_match.group(1)
                grid_start = grid_match.start()

                for dt_match in re.finditer(r"<dt>", grid_content):
                    line_num = content[: grid_start + dt_match.start()].count("\n") + 1
                    templates_with_issues.append((str(relative_path), line_num))

        if templates_with_issues:
            issue_lines = [f"  - {path}:{line}" for path, line in sorted(templates_with_issues)]
            pytest.fail(
                "Templates using raw <dt> inside c-detail_grid (use <c-detail_row> instead):\n" + "\n".join(issue_lines)
            )


class TestNestedForms:
    """Tests to prevent nested <form> tags, which cause browser validation bugs."""

    def test_no_nested_forms(self) -> None:
        """Templates must not contain nested <form> tags (invalid HTML)."""
        templates_with_nested_forms: list[tuple[str, int, int]] = []

        for template_path in get_all_template_files():
            if is_cotton_component(template_path):
                continue

            content = template_path.read_text()
            relative_path = template_path.relative_to(TEMPLATES_DIR)

            # Track form nesting depth
            depth = 0
            for match in re.finditer(r"<(/?)form[\s>]", content, re.IGNORECASE):
                is_closing = match.group(1) == "/"
                line_num = content[: match.start()].count("\n") + 1

                if is_closing:
                    depth = max(0, depth - 1)
                else:
                    depth += 1
                    if depth > 1:
                        templates_with_nested_forms.append((str(relative_path), line_num, depth))

        if templates_with_nested_forms:
            issue_lines = [
                f"  - {path}:{line} (depth {depth})" for path, line, depth in sorted(templates_with_nested_forms)
            ]
            pytest.fail(
                "Templates with nested <form> tags (causes browser validation bugs):\n" + "\n".join(issue_lines)
            )


class TestScrollableLayout:
    """Tests to ensure pages with tables allow horizontal scrolling."""

    def test_module_does_not_clip_overflow(self) -> None:
        """The .module class must not use overflow:hidden (clips wide tables)."""
        css = (STATIC_DIR / "css" / "app.css").read_text()
        # Find all .module { ... } blocks (not .module-something or .module > child)
        for match in re.finditer(r"\.module\s*\{([^}]+)\}", css):
            block = match.group(1)
            assert "overflow" not in block or "hidden" not in block, (
                ".module must not use overflow:hidden — it clips wide content. "
                "Use overflow:visible and let .results handle table scrolling."
            )

    def test_results_wrapper_allows_horizontal_scroll(self) -> None:
        """The .results wrapper must have overflow-x:auto for wide tables."""
        css = (STATIC_DIR / "css" / "app.css").read_text()
        results_blocks = [m.group(1) for m in re.finditer(r"\.results\s*\{([^}]+)\}", css)]
        assert results_blocks, ".results rule missing from app.css"
        has_overflow_x = any("overflow-x" in block and "auto" in block for block in results_blocks)
        assert has_overflow_x, ".results must have overflow-x:auto for horizontal table scrolling"

    def test_table_component_renders_results_wrapper(self) -> None:
        """The c-table component must wrap tables in a .results div."""
        table_template = (TEMPLATES_DIR / "cotton" / "table.html").read_text()
        assert re.search(r'class="results"', table_template), (
            'c-table component must wrap <table> in <div class="results"> for scroll support'
        )


class TestAlpineCSPCompatibility:
    """Ensure Alpine.js expressions work with the CSP build (no eval).

    The Alpine CSP build only supports simple property access (x-show="loading")
    and method references without parentheses (@click="toggle"). Expressions like
    !prop, a > b, fn(), a && b, {key: val} all require eval() and will silently
    fail at runtime.
    """

    # Alpine directives that contain expressions.
    # Captures (directive_name, value).
    ALPINE_DIRECTIVE_RE = re.compile(
        r"(?<![:\w])"
        r"("
        r"x-(?:show|if|text|html|model|for|init|effect|bind|on)(?::[\w.\-]+)?"
        r"|@[\w.\-]+"
        r"|::[\w][\w\-]*"
        r"|:[\w][\w\-]*"
        r')\s*=\s*"([^"]*)"',
    )

    # Simple property path: loading, criterion.label, $store.name.prop
    SIMPLE_EXPR_RE = re.compile(r"^[a-zA-Z_$][\w$]*(\.[a-zA-Z_$][\w$]*)*$")

    # x-for: (item, index) in collection OR item in collection
    X_FOR_RE = re.compile(
        r"^\(?\s*[a-zA-Z_]\w*\s*(?:,\s*[a-zA-Z_]\w*\s*)?\)?\s+in\s+"
        r"[a-zA-Z_$][\w$]*(\.[a-zA-Z_$][\w$]*)*$"
    )

    def test_alpine_expressions_are_csp_compatible(self) -> None:
        """All Alpine directive values must be simple property paths."""
        violations: list[tuple[str, int, str, str]] = []

        for template_path in get_all_template_files():
            content = template_path.read_text()
            relative = str(template_path.relative_to(TEMPLATES_DIR))

            for match in self.ALPINE_DIRECTIVE_RE.finditer(content):
                directive = match.group(1)
                value = match.group(2).strip()

                if not value:
                    continue

                # Django template tags are server-side rendered, not Alpine expressions
                if "{{" in value or "{%" in value:
                    continue

                # x-for has its own syntax: (item, index) in collection
                if directive == "x-for":
                    if not self.X_FOR_RE.match(value):
                        line = content[: match.start()].count("\n") + 1
                        violations.append((relative, line, directive, value))
                    continue

                if not self.SIMPLE_EXPR_RE.match(value):
                    line = content[: match.start()].count("\n") + 1
                    violations.append((relative, line, directive, value))

        if violations:
            lines = [f'  - {path}:{line} {d}="{v}"' for path, line, d, v in sorted(violations)]
            pytest.fail(
                "Alpine expressions incompatible with CSP build "
                "(move logic to computed getters in Alpine.data):\n" + "\n".join(lines)
            )


class TestFormFlexLayout:
    """Prevent <form class="d-flex"> with buttons alongside fields.

    Buttons should be in a separate <c-button_row> below fields, not
    floating inline.  The correct pattern wraps fields in an inner
    <div class="d-flex ..."> and places buttons in <c-button_row>.
    """

    # <form ... class="... d-flex ..." ...> (d-flex directly on the form tag)
    FORM_DFLEX_RE = re.compile(
        r"<form\b[^>]*\bclass=\"[^\"]*\bd-flex\b[^\"]*\"[^>]*>",
        re.DOTALL,
    )

    def test_no_d_flex_on_form_with_fields_and_buttons(self) -> None:
        """Forms with d-flex must not mix c-form_field and c-button as siblings."""
        violations: list[tuple[str, int]] = []

        for template_path in get_all_template_files():
            if is_cotton_component(template_path):
                continue

            content = template_path.read_text()
            relative = str(template_path.relative_to(TEMPLATES_DIR))

            for match in self.FORM_DFLEX_RE.finditer(content):
                # Find the matching </form>
                form_start = match.start()
                end = content.find("</form>", form_start)
                if end == -1:
                    continue

                form_body = content[form_start:end]
                has_field = "<c-form_field" in form_body or "<c-form_row" in form_body
                has_button = "<c-button" in form_body

                if has_field and has_button:
                    line = content[:form_start].count("\n") + 1
                    violations.append((relative, line))

        if violations:
            lines = [f"  - {path}:{line}" for path, line in sorted(violations)]
            pytest.fail(
                "Forms using d-flex with fields and buttons as siblings "
                "(wrap fields in <div class=\"d-flex ...\"> and use <c-button_row>):\n"
                + "\n".join(lines)
            )


class TestCottonAttrsPassthrough:
    """Ensure Cotton components include {{ attrs }} for attribute passthrough.

    Without {{ attrs }}, any undeclared attributes (like Alpine directives
    x-show, :class, @click) are silently dropped from the rendered HTML.
    """

    COTTON_DIR = TEMPLATES_DIR / "cotton"

    # Fragment components with no single root element where {{ attrs }} can't go
    FRAGMENT_COMPONENTS = {
        "detail_row.html",  # renders <dt> + <dd> siblings
        "pagination.html",  # conditional <p> wrapper
    }

    def test_cotton_components_include_attrs(self) -> None:
        """All Cotton components with a root element must include {{ attrs }}."""
        missing: list[str] = []

        for path in sorted(self.COTTON_DIR.glob("*.html")):
            if path.name in self.FRAGMENT_COMPONENTS:
                continue

            content = path.read_text()
            if "{{ attrs }}" not in content:
                missing.append(path.name)

        if missing:
            pytest.fail(
                "Cotton components missing {{ attrs }} (Alpine attributes will be silently dropped):\n"
                + "\n".join(f"  - cotton/{name}" for name in missing)
            )
