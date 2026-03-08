"""Tests for NAV_MAPPING consistency with URL configuration."""

import pytest
from django.urls import NoReverseMatch, reverse

from core.context_processors import NAV_MAPPING

# App namespaces used in the project — URL names in NAV_MAPPING may be
# registered under one of these prefixes (e.g. "submit_red_score" is
# actually "scoring:submit_red_score").
_APP_NAMESPACES = ("scoring", "challenges", "registration", "packets", "ticketing")


def _is_resolvable(url_name: str) -> bool:
    """Check if a URL name can be resolved, with or without app namespace prefix."""
    candidates = [url_name] + [f"{ns}:{url_name}" for ns in _APP_NAMESPACES]
    for candidate in candidates:
        try:
            reverse(candidate)
            return True
        except NoReverseMatch as e:
            # "not a valid view function or pattern name" means the name
            # doesn't exist at all.  Any other NoReverseMatch (e.g. missing
            # positional args) means the name IS registered — it just needs
            # arguments we can't provide here.
            if "is not a valid view function or pattern name" not in str(e):
                return True
    return False


@pytest.mark.django_db
class TestNavMapping:
    def test_all_nav_mapping_url_names_are_resolvable(self):
        """Every key in NAV_MAPPING must be a valid Django URL name."""
        unresolvable = [name for name in NAV_MAPPING if not _is_resolvable(name)]
        assert not unresolvable, f"NAV_MAPPING contains invalid URL names: {unresolvable}"

    def test_nav_mapping_values_are_tuples(self):
        """All NAV_MAPPING values must be (nav, subnav) string tuples."""
        for url_name, value in NAV_MAPPING.items():
            assert isinstance(value, tuple), f"{url_name}: expected tuple, got {type(value)}"
            assert len(value) == 2, f"{url_name}: expected 2-tuple, got {len(value)}-tuple"
            assert isinstance(value[0], str), f"{url_name}: nav must be str"
            assert isinstance(value[1], str), f"{url_name}: subnav must be str"
