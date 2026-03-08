"""Tests for NAV_MAPPING consistency with URL configuration."""

import pytest
from django.urls import NoReverseMatch, reverse

from core.context_processors import NAV_MAPPING


@pytest.mark.django_db
class TestNavMapping:
    def test_all_nav_mapping_url_names_are_resolvable(self):
        """Every key in NAV_MAPPING must be a valid Django URL name."""
        unresolvable = []
        for url_name in NAV_MAPPING:
            try:
                # Some URLs require arguments - we just check the name exists
                reverse(url_name)
            except NoReverseMatch as e:
                # Check if it failed because of missing args (name exists but needs params)
                # vs the name not existing at all
                if "is not a valid view function or pattern name" in str(e):
                    unresolvable.append(url_name)
                # If it failed due to missing args, the name is valid
        assert not unresolvable, f"NAV_MAPPING contains invalid URL names: {unresolvable}"

    def test_nav_mapping_values_are_tuples(self):
        """All NAV_MAPPING values must be (nav, subnav) string tuples."""
        for url_name, value in NAV_MAPPING.items():
            assert isinstance(value, tuple), f"{url_name}: expected tuple, got {type(value)}"
            assert len(value) == 2, f"{url_name}: expected 2-tuple, got {len(value)}-tuple"
            assert isinstance(value[0], str), f"{url_name}: nav must be str"
            assert isinstance(value[1], str), f"{url_name}: subnav must be str"
