"""Consistency enforcement tests.

These tests scan the codebase for known anti-patterns and fail if code
deviates from established shared utilities.  They run as part of the
normal test suite (and therefore ``deploy.sh``), preventing regressions.

To add an exemption, add the file path to the relevant ``EXEMPT_*`` set
with a comment explaining why.
"""

import re
from pathlib import Path

import pytest

WEB_DIR = Path(__file__).parent.parent.parent  # web/
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"
VIEWS_DIRS = [
    WEB_DIR / "scoring" / "views",
    WEB_DIR / "ticketing" / "views",
    WEB_DIR / "challenges" / "views.py",
    WEB_DIR / "packets" / "views.py",
]


def _get_template_files() -> list[Path]:
    return list(TEMPLATES_DIR.rglob("*.html"))


def _get_js_files() -> list[Path]:
    return list(STATIC_DIR.rglob("*.js"))


def _get_view_files() -> list[Path]:
    files = []
    for entry in VIEWS_DIRS:
        if entry.is_dir():
            files.extend(entry.glob("*.py"))
        elif entry.is_file():
            files.append(entry)
    return files


def _relative(path: Path) -> str:
    return str(path.relative_to(WEB_DIR))


# ---------------------------------------------------------------------------
# Template / JS consistency
# ---------------------------------------------------------------------------


class TestSharedJSUtilities:
    """Enforce use of utils.js shared functions instead of inline JS."""

    UTILS_JS = STATIC_DIR / "js" / "utils.js"

    def test_no_inline_csrf_header(self) -> None:
        """Templates and JS must use getCSRFToken() from utils.js,
        not build the X-CSRFToken header inline."""
        violations: list[tuple[str, int]] = []

        for path in _get_template_files() + _get_js_files():
            if path == self.UTILS_JS:
                continue
            # Cotton components never have JS
            if "cotton" in path.parts:
                continue

            content = path.read_text()
            for match in re.finditer(r"X-CSRFToken", content):
                # Allowed: using getCSRFToken() with the header
                context = content[max(0, match.start() - 80) : match.end() + 80]
                if "getCSRFToken()" in context:
                    continue
                line = content[: match.start()].count("\n") + 1
                violations.append((_relative(path), line))

        if violations:
            lines = [f"  - {p}:{ln}" for p, ln in sorted(violations)]
            pytest.fail("Inline X-CSRFToken header (use getCSRFToken() from utils.js):\n" + "\n".join(lines))

    def test_no_inline_csrf_from_dom(self) -> None:
        """Templates must not read CSRF token from DOM elements."""
        pattern = re.compile(r"querySelector.*csrfmiddlewaretoken|csrfmiddlewaretoken.*querySelector")
        violations: list[tuple[str, int]] = []

        for path in _get_template_files():
            if "cotton" in path.parts:
                continue
            content = path.read_text()
            for match in pattern.finditer(content):
                line = content[: match.start()].count("\n") + 1
                violations.append((_relative(path), line))

        if violations:
            lines = [f"  - {p}:{ln}" for p, ln in sorted(violations)]
            pytest.fail("Inline CSRF from DOM (use getCSRFToken() from utils.js):\n" + "\n".join(lines))

    def test_no_inline_ndjson_reader(self) -> None:
        """Templates must use wcStream() from utils.js, not inline getReader()."""
        violations: list[tuple[str, int]] = []

        for path in _get_template_files():
            if "cotton" in path.parts:
                continue
            content = path.read_text()
            for match in re.finditer(r"getReader\(\)", content):
                line = content[: match.start()].count("\n") + 1
                violations.append((_relative(path), line))

        if violations:
            lines = [f"  - {p}:{ln}" for p, ln in sorted(violations)]
            pytest.fail("Inline getReader() stream parsing (use wcStream() from utils.js):\n" + "\n".join(lines))

    def test_no_inline_text_decoder(self) -> None:
        """Templates must use wcStream() instead of inline TextDecoder."""
        violations: list[tuple[str, int]] = []

        for path in _get_template_files():
            if "cotton" in path.parts:
                continue
            content = path.read_text()
            for match in re.finditer(r"new TextDecoder", content):
                line = content[: match.start()].count("\n") + 1
                violations.append((_relative(path), line))

        if violations:
            lines = [f"  - {p}:{ln}" for p, ln in sorted(violations)]
            pytest.fail("Inline TextDecoder (use wcStream() from utils.js):\n" + "\n".join(lines))


class TestBulkSelectMixin:
    """Enforce use of bulkSelectMixin() from utils.js."""

    def test_no_inline_selectable_ids(self) -> None:
        """Templates must use bulkSelectMixin(), not define selectableIds inline."""
        violations: list[tuple[str, int]] = []

        for path in _get_template_files():
            if "cotton" in path.parts:
                continue
            content = path.read_text()
            for match in re.finditer(r"selectableIds\s*:", content):
                line = content[: match.start()].count("\n") + 1
                violations.append((_relative(path), line))

        if violations:
            lines = [f"  - {p}:{ln}" for p, ln in sorted(violations)]
            pytest.fail("Inline selectableIds definition (use bulkSelectMixin() from utils.js):\n" + "\n".join(lines))


# ---------------------------------------------------------------------------
# Python view consistency
# ---------------------------------------------------------------------------


class TestFilterSortPaginate:
    """Enforce use of filter_sort_paginate() from core.utils."""

    # Files that are exempt from this check (with reasons)
    EXEMPT_FILES = {
        # inject_grades_review materializes queryset for outlier calculation
        "scoring/views/injects.py",
        # review_inject_feedback has no pagination currently
        # Non-view files that use Paginator for different purposes
        "core/utils.py",
    }

    def test_no_inline_paginator_in_views(self) -> None:
        """View files should use filter_sort_paginate() instead of raw Paginator."""
        violations: list[tuple[str, int]] = []

        for path in _get_view_files():
            relative = _relative(path)
            if relative in self.EXEMPT_FILES:
                continue
            content = path.read_text()
            for match in re.finditer(r"Paginator\(", content):
                line = content[: match.start()].count("\n") + 1
                violations.append((relative, line))

        if violations:
            lines = [f"  - {p}:{ln}" for p, ln in sorted(violations)]
            pytest.fail(
                "Inline Paginator usage in views "
                "(use filter_sort_paginate() from core.utils, "
                "or add to EXEMPT_FILES with reason):\n" + "\n".join(lines)
            )


class TestBulkApproveHelper:
    """Enforce use of bulk_approve() from core.utils for bulk ID processing."""

    # Files exempt from this check
    EXEMPT_FILES: set[str] = set()

    # Pattern: manual ID extraction loop (POST.getlist + loop with int() conversion)
    # This is a heuristic — catches the "for x in ids: int(x)" pattern
    MANUAL_ID_LOOP_RE = re.compile(
        r"\.getlist\([^)]+\).*?for\s+\w+\s+in\s+\w+.*?int\(\w+\)",
        re.DOTALL,
    )

    def test_no_manual_id_extraction_in_views(self) -> None:
        """View POST handlers should use bulk_approve() for ID extraction loops."""
        violations: list[tuple[str, int]] = []

        for path in _get_view_files():
            relative = _relative(path)
            if relative in self.EXEMPT_FILES:
                continue
            content = path.read_text()

            # Look for the pattern: getlist(...) followed by for loop with int()
            # within the same function (approximate: within 500 chars)
            for getlist_match in re.finditer(r"\.getlist\(", content):
                chunk = content[getlist_match.start() : getlist_match.start() + 500]
                if re.search(r"for\s+\w+\s+in\s+\w+.*?int\(\w+\)", chunk, re.DOTALL):
                    line = content[: getlist_match.start()].count("\n") + 1
                    violations.append((relative, line))

        if violations:
            lines = [f"  - {p}:{ln}" for p, ln in sorted(violations)]
            pytest.fail(
                "Manual ID extraction loop in views "
                "(use bulk_approve() from core.utils, "
                "or add to EXEMPT_FILES with reason):\n" + "\n".join(lines)
            )
