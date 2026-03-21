"""Lint test: all POST data must go through Django forms.

Raw request.POST access bypasses CharField max_length validation and other
form-level protections. This test ensures views always use Django form classes.
"""

import re
from pathlib import Path

import pytest

WEB_DIR = Path(__file__).parent.parent.parent  # web/

# Patterns that indicate raw POST data extraction
RAW_POST_PATTERNS = re.compile(
    r"""
    request\.POST\.get\(          # request.POST.get("field")
    | request\.POST\.getlist\(    # request.POST.getlist("field")
    | request\.POST\[             # request.POST["field"]
    """,
    re.VERBOSE,
)

# Files/dirs that are scanned
VIEW_GLOBS = [
    "**/views.py",
    "**/views/*.py",
    "**/admin_views/*.py",
]

# Paths to skip (relative to web/)
ALLOWLIST = {
    # Generic utility, not a view — field name is dynamic
    "core/utils.py",
}


def _get_view_files() -> list[Path]:
    """Collect all view files."""
    files: set[Path] = set()
    for glob in VIEW_GLOBS:
        files.update(WEB_DIR.glob(glob))
    return sorted(files)


def test_no_raw_post_access() -> None:
    """Views must use Django forms instead of raw request.POST access."""
    violations: list[str] = []

    for path in _get_view_files():
        rel = str(path.relative_to(WEB_DIR))
        if rel in ALLOWLIST:
            continue

        lines = path.read_text().splitlines()
        for i, line in enumerate(lines, 1):
            # Strip inline comments and skip comment-only lines
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            # Remove inline comment (naive but sufficient for this pattern)
            code_part = line.split("#")[0] if "#" in line else line

            if RAW_POST_PATTERNS.search(code_part):
                violations.append(f"  {rel}:{i}  {stripped.strip()}")

    if violations:
        pytest.fail("Raw request.POST access found — use a Django form class instead:\n" + "\n".join(violations))
