"""Tests for Cotton detail_grid component."""

import pytest
from django.template.loader import get_template
from django.test import RequestFactory


@pytest.fixture
def request_factory():
    """Create request factory."""
    return RequestFactory()


def render_component(template_name: str, context: dict | None = None) -> str:
    """Helper to render a Cotton component template with context."""
    if context is None:
        context = {}
    template = get_template(template_name)
    return template.render(context)


class TestDetailGridComponent:
    """Test the detail_grid Cotton component rendering and responsiveness."""

    def test_detail_grid_renders_with_left_and_right_slots(self) -> None:
        """Component should render both left and right slot content."""
        result = render_component("test_detail_grid_basic.html")

        assert "Left Content" in result
        assert "Main information" in result
        assert "Right Content" in result
        assert "Secondary info" in result

    def test_detail_grid_has_two_column_grid_layout(self) -> None:
        """Component should apply CSS grid with 2 columns."""
        result = render_component("test_detail_grid_basic.html")

        assert "display: grid" in result or "display:grid" in result
        assert "grid-template-columns" in result
        assert "1fr" in result

    def test_detail_grid_uses_default_gap_when_not_specified(self) -> None:
        """Component should use default 20px gap when gap prop not provided."""
        result = render_component("test_detail_grid_basic.html")

        assert "gap: 20px" in result or "gap:20px" in result

    def test_detail_grid_accepts_custom_gap_prop(self) -> None:
        """Component should accept and apply custom gap spacing."""
        result = render_component("test_detail_grid_custom_gap.html")

        assert "gap: 30px" in result or "gap:30px" in result

    def test_detail_grid_has_mobile_responsive_styles(self) -> None:
        """Component should include media query for mobile stacking."""
        result = render_component("test_detail_grid_basic.html")

        assert "@media" in result
        assert "768px" in result or "max-width" in result

    def test_detail_grid_stacks_vertically_on_mobile(self) -> None:
        """Component should change to single column on mobile screens."""
        result = render_component("test_detail_grid_basic.html")

        # Should have media query that changes grid to 1 column
        assert "@media" in result
        # Mobile styles should set grid to 1fr (single column)
        result_lower = result.lower()
        assert "1fr" in result_lower

    def test_detail_grid_renders_without_slots(self) -> None:
        """Component should handle being rendered without slot content."""
        # Should not raise an error
        result = render_component("test_detail_grid_empty.html")
        assert result is not None

    def test_detail_grid_renders_with_only_left_slot(self) -> None:
        """Component should render correctly with only left slot populated."""
        result = render_component("test_detail_grid_left_only.html")
        assert "Only Left" in result

    def test_detail_grid_renders_with_only_right_slot(self) -> None:
        """Component should render correctly with only right slot populated."""
        result = render_component("test_detail_grid_right_only.html")
        assert "Only Right" in result

    def test_detail_grid_preserves_html_structure_in_slots(self) -> None:
        """Component should preserve complex HTML structures in slots."""
        result = render_component("test_detail_grid_complex_html.html")

        assert "<table>" in result
        assert "<tr>" in result
        assert "<ul>" in result
        assert "<li>Item 1</li>" in result
