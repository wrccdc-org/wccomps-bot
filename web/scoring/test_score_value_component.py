"""
Tests for c-score_value Cotton component.

This component displays numeric score values with automatic color coding.
Tests verify rendering behavior through actual component usage rather than
checking template file contents.
"""

import pytest
from django.template import Context, Template

pytestmark = pytest.mark.django_db


class TestScoreValueComponentRendering:
    """Test c-score_value component rendering behavior."""

    def _render_component(self, value: str, fmt: str = "") -> str:
        """Render the score_value component with given parameters."""
        template_str = f'{{% load cotton %}}<c-score_value value="{value}" format="{fmt}" />'
        template = Template(template_str)
        return template.render(Context({}))

    def test_positive_value_renders_with_positive_class(self) -> None:
        """Positive values should render with score-positive class."""
        html = self._render_component("100")
        assert "score-positive" in html
        assert "100" in html

    def test_negative_value_renders_with_negative_class(self) -> None:
        """Negative values should render with score-negative class."""
        html = self._render_component("-50")
        assert "score-negative" in html
        assert "-50" in html

    def test_zero_value_renders_with_zero_class(self) -> None:
        """Zero values should render with score-zero class."""
        html = self._render_component("0")
        assert "score-zero" in html
        assert "0" in html

    def test_signed_format_adds_plus_to_positive(self) -> None:
        """Signed format should add + prefix to positive values."""
        html = self._render_component("75", "signed")
        assert "+75" in html or "+<" in html  # + might be before or inside span

    def test_signed_format_keeps_minus_on_negative(self) -> None:
        """Signed format should keep - prefix on negative values."""
        html = self._render_component("-25", "signed")
        assert "-25" in html

    def test_renders_as_inline_element(self) -> None:
        """Component should render as inline element (span)."""
        html = self._render_component("100")
        assert "<span" in html
        assert "</span>" in html

    @pytest.mark.parametrize(
        "value,expected_class",
        [
            ("1", "score-positive"),
            ("999", "score-positive"),
            ("-1", "score-negative"),
            ("-999", "score-negative"),
            ("0", "score-zero"),
        ],
    )
    def test_various_values_get_correct_class(self, value: str, expected_class: str) -> None:
        """Various values should get the appropriate CSS class."""
        html = self._render_component(value)
        assert expected_class in html
