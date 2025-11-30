#!/usr/bin/env python3
"""Find raw HTML patterns that could be replaced with Cotton components."""

import re
from collections import defaultdict
from pathlib import Path

TEMPLATES_DIR = Path("web/templates")
SKIP_DIRS = {"cotton", "admin", "emails"}  # Skip component definitions and admin
SKIP_FILES = {"base.html", "base_site.html"}

# Patterns to check for (pattern, description, severity)
PATTERNS = [
    # Tables
    (r"<table\s", "Raw <table> not wrapped in c-table", "high"),
    (r"<thead>", "Raw <thead> (should use c-slot name='headers')", "high"),
    (r"<tbody>", "Raw <tbody> (c-table handles this)", "medium"),
    (r"<th>(?!.*c-table_header)", "Raw <th> not using c-table_header", "medium"),
    (r'<th\s+scope="col">', "Raw <th scope='col'> not using c-table_header", "medium"),
    # Divs with specific classes
    (r'<div\s+class="results"', "Raw div.results (use c-table)", "high"),
    (r'<div\s+class="module"', "Raw div.module (use c-module)", "high"),
    (r'<div\s+class="action-box', "Raw div.action-box (use c-action_box)", "high"),
    (r'<div\s+class="submit-row', "Raw div.submit-row (use c-button_row)", "medium"),
    (r'<div\s+class="form-row', "Raw div.form-row (use c-form_field)", "medium"),
    (r'<div\s+class="fieldset', "Raw div.fieldset (use c-fieldset)", "medium"),
    (r'<div\s+class="d-flex\s+gap', "Raw div.d-flex gap (consider c-button_row)", "low"),
    # Forms
    (r'<input\s+type="text"[^>]*>\s*$', "Unwrapped text input (consider c-form_field)", "low"),
    (r"<select[^>]*>\s*$", "Unwrapped select (consider c-filter_field or c-form_field)", "low"),
    (r"<textarea[^>]*>\s*$", "Unwrapped textarea (consider c-form_field)", "low"),
    # Links and buttons (only outside cotton components)
    (r'<a\s+href="/', "Hardcoded URL (use {% url %})", "high"),
    (r'action="/', "Hardcoded form action URL (use {% url %})", "high"),
    # Semantic elements that might benefit from components
    (r'<h2\s+class="', "h2 with class (consider c-section_header)", "low"),
    (r'<h3\s+class="', "h3 with class (consider c-fieldset heading)", "low"),
]


def find_patterns_in_file(filepath: Path) -> list[tuple[int, str, str, str]]:
    """Find patterns in a file. Returns list of (line_num, line, pattern_desc, severity)."""
    findings = []
    try:
        content = filepath.read_text()
        lines = content.split("\n")

        for line_num, line in enumerate(lines, 1):
            # Skip lines that are inside Cotton components
            stripped = line.strip()
            if stripped.startswith(("<c-", "</c-")):
                continue

            for pattern, desc, severity in PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    # Additional checks to reduce false positives
                    if "c-table" in line and "Raw <table>" in desc:
                        continue
                    if "c-module" in line and "div.module" in desc:
                        continue
                    if "<c-slot" in line:
                        continue

                    findings.append((line_num, line.strip()[:80], desc, severity))

    except Exception as e:
        print(f"Error reading {filepath}: {e}")

    return findings


def main():
    all_findings = defaultdict(list)
    severity_counts = defaultdict(int)

    for html_file in TEMPLATES_DIR.rglob("*.html"):
        # Skip excluded directories and files
        rel_path = html_file.relative_to(TEMPLATES_DIR)
        if any(part in SKIP_DIRS for part in rel_path.parts):
            continue
        if html_file.name in SKIP_FILES:
            continue

        findings = find_patterns_in_file(html_file)
        if findings:
            all_findings[str(rel_path)] = findings
            for _, _, _, severity in findings:
                severity_counts[severity] += 1

    # Print summary
    print("=" * 80)
    print("RAW HTML PATTERNS THAT COULD BE REPLACED WITH COTTON COMPONENTS")
    print("=" * 80)
    high = severity_counts["high"]
    medium = severity_counts["medium"]
    low = severity_counts["low"]
    print(f"\nSummary: {high} high, {medium} medium, {low} low priority issues\n")

    # Print findings grouped by severity
    for severity in ["high", "medium", "low"]:
        severity_findings = []
        for filepath, findings in sorted(all_findings.items()):
            for line_num, line, desc, sev in findings:
                if sev == severity:
                    severity_findings.append((filepath, line_num, line, desc))

        if severity_findings:
            print(f"\n{'=' * 40}")
            print(f"{severity.upper()} PRIORITY ({len(severity_findings)} issues)")
            print(f"{'=' * 40}\n")

            current_file = None
            for filepath, line_num, line, desc in severity_findings:
                if filepath != current_file:
                    print(f"\n📁 {filepath}")
                    current_file = filepath
                print(f"  L{line_num}: {desc}")
                print(f"       {line[:70]}...")


if __name__ == "__main__":
    main()
