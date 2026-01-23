"""Template linting tests to enforce best practices."""

import re
from pathlib import Path

import pytest

TEMPLATES_DIR = Path(__file__).parent.parent.parent / "templates"


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
