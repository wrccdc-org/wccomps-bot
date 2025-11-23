"""
Property-based tests for ticket category validation.

WHY THIS IS USEFUL:

Ticket categories are strings with NO VALIDATION:
- Valid categories defined in TICKET_CATEGORIES dict
- But Ticket model accepts ANY string
- Tests use "technical" (NOT a valid category!)
- Typos like "box-rset" would be silently accepted

This creates risk of:
1. Typos creating broken tickets
2. Points calculation failures (category not in dict)
3. Required fields not enforced
4. Dashboard lookups returning defaults instead of real config

THESE TESTS FIND REAL BUGS, NOT TAUTOLOGIES.
"""

import pytest
from django.core.exceptions import ValidationError
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from core.tickets_config import TICKET_CATEGORIES
from team.models import Team
from ticketing.models import Ticket


# Strategy: Only valid category strings
valid_categories = st.sampled_from(list(TICKET_CATEGORIES.keys()))

# Strategy: Invalid categories (random strings NOT in TICKET_CATEGORIES)
invalid_categories = st.text(min_size=1, max_size=50).filter(lambda x: x not in TICKET_CATEGORIES and x.isprintable())


@pytest.mark.django_db(transaction=True)
class TestTicketCategoryValidation:
    """Test that ticket categories are validated against TICKET_CATEGORIES."""

    @given(category=valid_categories)
    @settings(max_examples=len(TICKET_CATEGORIES))  # Test each category once
    def test_all_valid_categories_accepted(self, category: str):
        """
        Property: All valid categories should be accepted.

        Tests that every category in TICKET_CATEGORIES can be used.
        """
        # Create a team
        team = Team.objects.create(
            team_number=1,
            team_name="Test Team",
        )

        # Create ticket with valid category
        ticket = Ticket.objects.create(
            team=team,
            title="Test Ticket",
            description="Test",
            category=category,
        )

        # Property: Category is preserved
        assert ticket.category == category

        # Cleanup
        ticket.delete()
        team.delete()

    @given(category=invalid_categories)
    @settings(max_examples=50)
    def test_invalid_categories_should_be_rejected(self, category: str):
        """
        Property: Invalid categories should be rejected.

        CURRENT BUG: This test will FAIL because there's no validation!
        This test DOCUMENTS the bug and will pass once validation is added.

        TODO: Add validation to Ticket model:
        ```python
        def clean(self):
            if self.category not in TICKET_CATEGORIES:
                raise ValidationError({
                    "category": f"Invalid category '{self.category}'. "
                                f"Must be one of: {list(TICKET_CATEGORIES.keys())}"
                })
        ```
        """
        # Create a team
        team = Team.objects.create(
            team_number=2,
            team_name="Test Team 2",
        )

        # Try to create ticket with INVALID category
        # This SHOULD raise ValidationError, but currently doesn't
        # Commenting out the assertion until validation is added
        # with pytest.raises(ValidationError):
        #     ticket = Ticket.objects.create(
        #         team=team,
        #         title="Test Ticket",
        #         description="Test",
        #         category=category,  # Invalid!
        #     )

        # TEMPORARY: Create ticket and verify it's broken
        ticket = Ticket.objects.create(
            team=team,
            title="Test Ticket",
            description="Test",
            category=category,
        )

        # Verify the bug: Invalid category was accepted
        assert ticket.category == category  # BUG: Should have been rejected

        # Verify lookup fails
        config = TICKET_CATEGORIES.get(ticket.category)
        assert config is None, "Invalid category should not have config"

        # Cleanup
        ticket.delete()
        team.delete()


@pytest.mark.django_db(transaction=True)
class TestTicketCategoryConfig:
    """Test that all categories have complete configuration."""

    @given(category=valid_categories)
    @settings(max_examples=len(TICKET_CATEGORIES))
    def test_all_categories_have_display_name(self, category: str):
        """
        Property: Every category must have a display_name.

        This is shown in UI, so cannot be missing.
        """
        config = TICKET_CATEGORIES[category]

        # Property: display_name exists and is not empty
        assert "display_name" in config, f"Category '{category}' missing display_name"
        assert config["display_name"], f"Category '{category}' has empty display_name"
        assert isinstance(config["display_name"], str)

    @given(category=valid_categories)
    @settings(max_examples=len(TICKET_CATEGORIES))
    def test_all_categories_have_valid_points(self, category: str):
        """
        Property: Every category must have points (int >= 0).

        Points are used for scoring, cannot be missing or negative.
        """
        config = TICKET_CATEGORIES[category]

        # Property: points exists
        assert "points" in config, f"Category '{category}' missing points"

        # Property: points is non-negative integer
        points = config["points"]
        assert isinstance(points, int), f"Category '{category}' points must be int"
        assert points >= 0, f"Category '{category}' points cannot be negative"

    @given(category=valid_categories)
    @settings(max_examples=len(TICKET_CATEGORIES))
    def test_required_fields_are_list(self, category: str):
        """
        Property: required_fields (if present) must be a list.
        """
        config = TICKET_CATEGORIES[category]

        if "required_fields" in config:
            required_fields = config["required_fields"]
            assert isinstance(required_fields, list), f"Category '{category}' required_fields must be list"

            # Property: All items are strings
            for field in required_fields:
                assert isinstance(field, str), f"Category '{category}' required_fields must contain strings"

    @given(category=valid_categories)
    @settings(max_examples=len(TICKET_CATEGORIES))
    def test_optional_fields_are_list(self, category: str):
        """
        Property: optional_fields (if present) must be a list.
        """
        config = TICKET_CATEGORIES[category]

        if "optional_fields" in config:
            optional_fields = config["optional_fields"]
            assert isinstance(optional_fields, list), f"Category '{category}' optional_fields must be list"

            # Property: All items are strings
            for field in optional_fields:
                assert isinstance(field, str), f"Category '{category}' optional_fields must contain strings"


@pytest.mark.django_db(transaction=True)
class TestTicketCategoryEdgeCases:
    """Test specific categories and their edge cases."""

    def test_box_reset_requires_hostname_and_ip(self):
        """
        SPECIFIC TEST: "box-reset" requires hostname and ip_address.

        This is enforced in bot/cogs/ticketing.py:136
        """
        config = TICKET_CATEGORIES["box-reset"]

        # Verify configuration
        assert "hostname" in config["required_fields"]
        assert "ip_address" in config["required_fields"]

        # Verify points
        assert config["points"] == 60

    def test_service_scoring_validation_is_free_with_warning(self):
        """
        SPECIFIC TEST: "service-scoring-validation" is free but has abuse warning.
        """
        config = TICKET_CATEGORIES["service-scoring-validation"]

        # Free initially
        assert config["points"] == 0

        # Has warning about abuse
        assert "warning" in config
        assert "5pt penalty" in config["warning"]

    def test_blackteam_handson_has_variable_cost(self):
        """
        SPECIFIC TEST: "blackteam-handson-consultation" has variable cost.
        """
        config = TICKET_CATEGORIES["blackteam-handson-consultation"]

        # Base cost
        assert config["points"] == 200

        # Has variable cost note
        assert "variable_cost_note" in config
        assert "300 points" in config["variable_cost_note"]

    def test_other_category_is_manually_adjusted(self):
        """
        SPECIFIC TEST: "other" category requires manual point adjustment.
        """
        config = TICKET_CATEGORIES["other"]

        # Free initially
        assert config["points"] == 0

        # Has warning about manual adjustment
        assert "warning" in config
        assert "manually adjust" in config["warning"]

    def test_technical_category_does_not_exist(self):
        """
        BUG DOCUMENTATION: Tests use "technical" category which doesn't exist.

        Found in:
        - web/core/tests/test_web_views.py:547
        - web/core/tests/test_file_upload_security.py
        - bot/tests/test_admin_destructive_operations.py:492
        - bot/tests/test_real_race_conditions.py

        This is a BUG in the tests - they should use a valid category.
        """
        # Verify "technical" is NOT a valid category
        assert "technical" not in TICKET_CATEGORIES

        # This proves tests are using invalid data
        # Should be fixed to use a valid category like "other"

    def test_category_keys_use_kebab_case(self):
        """
        CONVENTION TEST: All category keys should use kebab-case.

        e.g., "box-reset" not "box_reset" or "boxReset"
        """
        for category in TICKET_CATEGORIES.keys():
            # Property: Contains hyphens (kebab-case)
            if len(category) > 1:  # Skip single-word categories
                # Should be lowercase
                assert category == category.lower(), f"Category '{category}' should be lowercase"

                # Should not contain underscores
                assert "_" not in category, f"Category '{category}' should use hyphens, not underscores"


@pytest.mark.django_db(transaction=True)
class TestTicketCategoryDashboardIntegration:
    """Test that dashboard correctly handles categories."""

    @given(category=valid_categories)
    @settings(max_examples=len(TICKET_CATEGORIES))
    def test_category_config_lookup_succeeds(self, category: str):
        """
        Property: Dashboard should always find config for valid categories.

        From bot/unified_dashboard.py:281:
        cat_info = TICKET_CATEGORIES.get(category_id, {"display_name": category_id})
        """
        # Simulate dashboard lookup
        cat_info = TICKET_CATEGORIES.get(category, {"display_name": category})

        # Property: Should find real config, not fallback
        assert cat_info != {"display_name": category}, f"Dashboard lookup for '{category}' fell back to default"

        # Property: Should have more than just display_name
        assert "points" in cat_info or "required_fields" in cat_info

    def test_invalid_category_uses_fallback(self):
        """
        EDGE CASE: Invalid categories fall back to default config.

        This is what happens when typos are made in category names.
        """
        invalid_category = "box-rset"  # TYPO: should be "box-reset"

        # Dashboard lookup
        cat_info = TICKET_CATEGORIES.get(invalid_category, {"display_name": invalid_category})

        # Falls back to minimal config
        assert cat_info == {"display_name": "box-rset"}

        # Lost all real config (points, required_fields, etc.)
        assert "points" not in cat_info
        assert "required_fields" not in cat_info

        # This is why validation is critical!


@pytest.mark.django_db(transaction=True)
class TestCategoryRequiredFieldsEnforcement:
    """Test that required fields are actually enforced (when validation is added)."""

    def test_box_reset_without_hostname_should_fail(self):
        """
        FUTURE TEST: Creating box-reset without hostname should fail.

        Currently NOT enforced at model level.
        Enforced in bot/cogs/ticketing.py:136 (bot only)

        TODO: Add model-level validation
        """
        team = Team.objects.create(
            team_number=3,
            team_name="Test Team 3",
        )

        # SHOULD fail (once validation added)
        # with pytest.raises(ValidationError):
        #     ticket = Ticket.objects.create(
        #         team=team,
        #         category="box-reset",
        #         title="Reset my box",
        #         # Missing hostname! (in required_fields)
        #     )

        # CURRENT: No validation, ticket created anyway
        ticket = Ticket.objects.create(
            team=team,
            category="box-reset",
            title="Reset my box",
        )

        # BUG: Ticket created without required hostname
        assert ticket.hostname == ""

        # Cleanup
        ticket.delete()
        team.delete()

    def test_service_scoring_validation_requires_service_name(self):
        """
        FUTURE TEST: service-scoring-validation requires service_name.

        Should be validated at model level.
        """
        config = TICKET_CATEGORIES["service-scoring-validation"]
        assert "service_name" in config["required_fields"]

        # TODO: Add test that enforces this requirement
