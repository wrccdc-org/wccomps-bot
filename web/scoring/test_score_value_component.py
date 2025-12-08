"""
Tests for c-score_value Cotton component.

This component displays numeric score values with automatic color coding
via CSS classes:
- Positive values: score-positive class
- Negative values: score-negative class
- Zero: score-zero class
- Signed format adds +/- prefix for positive numbers

These tests verify the component template exists and contains the correct logic.
Full rendering tests are done through integration tests.
"""

from pathlib import Path

import pytest
from django.conf import settings

# Get template directory from Django settings
TEMPLATES_DIR = Path(settings.BASE_DIR) / "templates"
COTTON_DIR = TEMPLATES_DIR / "cotton"


@pytest.mark.django_db
class TestScoreValueComponent:
    """Test c-score_value component."""

    def test_component_file_exists(self) -> None:
        """Component template file should exist."""
        component_path = COTTON_DIR / "score_value.html"
        assert component_path.exists(), f"Component file should exist at {component_path}"

    def test_component_contains_color_logic(self) -> None:
        """Component should contain CSS class logic for positive/negative/zero."""
        content = (COTTON_DIR / "score_value.html").read_text()

        # Should contain CSS class for positive
        assert "score-positive" in content, "Should contain score-positive class for positive values"

        # Should contain CSS class for negative
        assert "score-negative" in content, "Should contain score-negative class for negative values"

        # Should contain CSS class for zero
        assert "score-zero" in content, "Should contain score-zero class for zero values"

    def test_component_contains_signed_format_logic(self) -> None:
        """Component should contain logic for signed format (+/-)."""
        content = (COTTON_DIR / "score_value.html").read_text()

        # Should check for signed format
        assert "signed" in content.lower(), "Should contain 'signed' format check"

        # Should contain plus sign logic
        assert "+" in content, "Should contain + prefix logic for signed format"

    def test_component_uses_span_element(self) -> None:
        """Component should use span element for inline display."""
        content = (COTTON_DIR / "score_value.html").read_text()

        assert "<span" in content, "Should use <span> tag for inline display"
        assert "</span>" in content, "Should close <span> tag"

    def test_component_has_default_vars(self) -> None:
        """Component should declare c-vars for value and format."""
        content = (COTTON_DIR / "score_value.html").read_text()

        assert "<c-vars" in content, "Should declare component variables with <c-vars>"
        assert "value" in content, "Should have 'value' prop"
        assert "format" in content, "Should have 'format' prop"
