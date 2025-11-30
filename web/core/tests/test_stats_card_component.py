"""Tests for stats_card Cotton component."""

import pytest
from django.template.loader import get_template

pytestmark = pytest.mark.django_db


class TestStatsCardComponent:
    """Test the stats_card component rendering and styling."""

    def test_renders_value_and_label(self):
        """Component should render the value and label text."""
        template = get_template("test_helpers/stats_card_test.html")
        rendered = template.render({"test_value": "42", "test_label": "Total Teams", "test_color": "primary"})

        assert "<c-stats_card" not in rendered, "Component should be resolved, not rendered as tag"
        assert "42" in rendered
        assert "Total Teams" in rendered

    def test_default_color_is_primary(self):
        """Component should use primary color (#417690) by default."""
        template = get_template("test_helpers/stats_card_test.html")
        rendered = template.render({"test_value": "42", "test_label": "Total Teams", "test_color": "primary"})

        assert "#417690" in rendered

    def test_success_color(self):
        """Component should use success color (#28a745) when color=success."""
        template = get_template("test_helpers/stats_card_test.html")
        rendered = template.render({"test_value": "+15", "test_label": "Points Gained", "test_color": "success"})

        assert "#28a745" in rendered
        assert "+15" in rendered
        assert "Points Gained" in rendered

    def test_warning_color(self):
        """Component should use warning color (#ffc107) when color=warning."""
        template = get_template("test_helpers/stats_card_test.html")
        rendered = template.render({"test_value": "3", "test_label": "Warnings", "test_color": "warning"})

        assert "#ffc107" in rendered

    def test_danger_color(self):
        """Component should use danger color (#dc3545) when color=danger."""
        template = get_template("test_helpers/stats_card_test.html")
        rendered = template.render({"test_value": "-5", "test_label": "Penalties", "test_color": "danger"})

        assert "#dc3545" in rendered
        assert "-5" in rendered
        assert "Penalties" in rendered

    def test_large_value_text_size(self):
        """Value should be displayed in large text."""
        template = get_template("test_helpers/stats_card_test.html")
        rendered = template.render({"test_value": "42", "test_label": "Total Teams", "test_color": "primary"})

        assert "font-size: 48px" in rendered

    def test_small_label_text_size(self):
        """Label should be displayed in small text below value."""
        template = get_template("test_helpers/stats_card_test.html")
        rendered = template.render({"test_value": "42", "test_label": "Total Teams", "test_color": "primary"})

        assert "font-size: 14px" in rendered

    def test_value_comes_before_label_in_dom(self):
        """Value should appear before label in the DOM structure."""
        template = get_template("test_helpers/stats_card_test.html")
        rendered = template.render({"test_value": "42", "test_label": "Total Teams", "test_color": "primary"})

        value_pos = rendered.find("42")
        label_pos = rendered.find("Total Teams")
        assert value_pos < label_pos

    def test_works_in_grid_layout(self):
        """Component should work within a grid layout."""
        template = get_template("test_helpers/stats_card_grid_test.html")
        rendered = template.render({})

        assert "42" in rendered
        assert "+15" in rendered
        assert "-5" in rendered
        assert "Total Teams" in rendered
        assert "Points Gained" in rendered
        assert "Penalties" in rendered
