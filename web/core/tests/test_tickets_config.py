"""Tests for ticket category config helpers."""

import pytest

from ticketing.models import TicketCategory

pytestmark = pytest.mark.django_db


@pytest.fixture
def sample_categories():
    """Create sample categories for testing (clears seeded data first)."""
    TicketCategory.objects.all().delete()
    cat1 = TicketCategory.objects.create(
        display_name="Box Reset",
        points=60,
        required_fields=["hostname", "ip_address"],
        optional_fields=[],
        sort_order=0,
    )
    cat2 = TicketCategory.objects.create(
        display_name="Other",
        points=0,
        required_fields=["description"],
        variable_points=True,
        user_creatable=True,
        sort_order=1,
    )
    cat3 = TicketCategory.objects.create(
        display_name="Admin Only",
        points=50,
        required_fields=["description"],
        user_creatable=False,
        sort_order=2,
    )
    return cat1, cat2, cat3


class TestGetCategoryConfig:
    def test_returns_config_dict(self, sample_categories):
        from core.tickets_config import get_category_config

        cat1 = sample_categories[0]
        config = get_category_config(cat1.id)
        assert config is not None
        assert config["display_name"] == "Box Reset"
        assert config["points"] == 60
        assert config["required_fields"] == ["hostname", "ip_address"]

    def test_returns_none_for_missing(self, db):
        from core.tickets_config import get_category_config

        assert get_category_config(9999) is None

    def test_returns_none_for_none(self, db):
        from core.tickets_config import get_category_config

        assert get_category_config(None) is None


class TestGetAllCategories:
    def test_returns_all(self, sample_categories):
        from core.tickets_config import get_all_categories

        cats = get_all_categories()
        assert len(cats) == 3

    def test_user_creatable_filter(self, sample_categories):
        from core.tickets_config import get_all_categories

        cats = get_all_categories(user_creatable_only=True)
        assert len(cats) == 2
        for config in cats.values():
            assert config.get("user_creatable", True) is True
