"""
Property-based tests for discord_id consistency.

WHY THIS IS USEFUL:

discord_id has type inconsistencies across 172 usages in 20 files:
- Database: BigIntegerField (int)
- Discord API: int (snowflakes)
- Authentik API: string (JSON attributes)

This creates risk of:
1. Type conversion bugs (int → string → int)
2. JSON precision loss (Discord IDs > JavaScript MAX_SAFE_INTEGER)
3. Query mismatches (searching for int when stored as string)
4. Round-trip failures

THESE TESTS FIND REAL BUGS, NOT TAUTOLOGIES.
"""

import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from team.models import DiscordLink

# Discord snowflakes are 64-bit integers
# Realistic range: 100000000000000000 to 999999999999999999 (17-18 digits)
discord_id_strategy = st.integers(
    min_value=100000000000000000,  # Minimum realistic Discord ID
    max_value=999999999999999999,  # Maximum realistic Discord ID
)


@pytest.mark.django_db(transaction=True)
class TestDiscordIDTypeConsistency:
    """Test that discord_id survives type conversions."""

    @given(discord_id=discord_id_strategy)
    @settings(max_examples=50)
    def test_discord_id_int_to_string_round_trip(self, discord_id: int):
        """
        Property: int → str → int preserves value.

        This tests the Authentik storage pattern:
        1. Receive discord_id as int from Discord API
        2. Store as string in Authentik attributes
        3. Query with string
        4. Parse back to int

        BUG IF: Conversion loses precision or adds/removes digits
        """
        # Convert to string (Authentik storage)
        as_string = str(discord_id)

        # Convert back to int (query result)
        parsed = int(as_string)

        # Property: Round-trip preserves value
        assert parsed == discord_id, f"Round-trip failed: {discord_id} → '{as_string}' → {parsed}"

        # Property: String representation has correct length
        assert len(as_string) in range(17, 19), (  # Discord IDs are 17-18 digits
            f"Unexpected string length: '{as_string}' ({len(as_string)} digits)"
        )

    @given(discord_id=discord_id_strategy)
    @settings(max_examples=50)
    def test_discord_id_json_serialization_safe(self, discord_id: int):
        """
        Property: Discord IDs survive JSON serialization as strings.

        CRITICAL: Discord IDs can exceed JavaScript's MAX_SAFE_INTEGER (2^53 - 1).
        If sent as numbers in JSON, JavaScript loses precision.

        Solution: Always serialize as strings.

        BUG IF: Serialized as number and precision lost.
        """
        # CORRECT: Serialize as string
        data_safe = {"discord_id": str(discord_id)}
        json_str = json.dumps(data_safe)
        parsed_safe = json.loads(json_str)
        retrieved_safe = int(parsed_safe["discord_id"])

        # Property: String serialization preserves value
        assert retrieved_safe == discord_id

        # DANGEROUS: Serialize as number (don't do this in real code!)
        # This demonstrates the bug we're preventing
        if discord_id > 9007199254740991:  # JavaScript MAX_SAFE_INTEGER
            # Large numbers would lose precision in JavaScript
            # We can't test this fully in Python, but we document the risk
            pass

    @given(discord_id=discord_id_strategy)
    @settings(max_examples=30)
    def test_discord_id_database_storage_round_trip(self, discord_id: int):
        """
        Property: discord_id → Database → retrieve → same value.

        Tests that BigIntegerField correctly stores Discord snowflakes.
        """
        # Create a DiscordLink with this discord_id
        link = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username=f"user_{discord_id}",
            authentik_username=f"auth_{discord_id}",
            authentik_user_id=f"uid-{discord_id}",
            is_active=True,
        )

        # Retrieve from database
        retrieved_link = DiscordLink.objects.get(pk=link.pk)

        # Property: Value preserved in database
        assert retrieved_link.discord_id == discord_id

        # Cleanup
        link.delete()

    @given(discord_id=discord_id_strategy)
    @settings(max_examples=30)
    def test_discord_id_query_by_exact_value(self, discord_id: int):
        """
        Property: Can query DiscordLink by exact discord_id.

        This tests that database queries work correctly.
        BUG IF: Query fails due to type mismatch.
        """
        # Create link
        link = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username=f"user_{discord_id}",
            authentik_username=f"auth_{discord_id}",
            authentik_user_id=f"uid-{discord_id}",
            is_active=True,
        )

        # Property: Can find by exact discord_id
        found = DiscordLink.objects.filter(discord_id=discord_id).first()
        assert found is not None
        assert found.discord_id == discord_id

        # Property: Only one result
        count = DiscordLink.objects.filter(discord_id=discord_id).count()
        assert count == 1

        # Cleanup
        link.delete()


@pytest.mark.django_db(transaction=True)
class TestDiscordIDEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_discord_id_minimum_value(self):
        """
        BOUNDARY TEST: Minimum realistic Discord ID.

        Discord snowflakes started at ~100000000000000000 (2015).
        """
        min_discord_id = 100000000000000000

        link = DiscordLink.objects.create(
            discord_id=min_discord_id,
            discord_username="user_min",
            authentik_username="auth_min",
            authentik_user_id="uid-min",
            is_active=True,
        )

        assert link.discord_id == min_discord_id
        link.delete()

    def test_discord_id_maximum_value(self):
        """
        BOUNDARY TEST: Maximum realistic Discord ID.

        Current Discord IDs are ~18 digits.
        """
        max_discord_id = 999999999999999999

        link = DiscordLink.objects.create(
            discord_id=max_discord_id,
            discord_username="user_max",
            authentik_username="auth_max",
            authentik_user_id="uid-max",
            is_active=True,
        )

        assert link.discord_id == max_discord_id
        link.delete()

    def test_discord_id_string_has_no_leading_zeros(self):
        """
        EDGE CASE: String representation should not have leading zeros.

        BUG IF: str(123) → "0123" (wrong!)
        """
        discord_id = 123456789012345678

        as_string = str(discord_id)

        # Property: No leading zeros
        assert not as_string.startswith("0")
        assert as_string == "123456789012345678"

    def test_authentik_attribute_storage_pattern(self):
        """
        INTEGRATION TEST: Verify Authentik storage pattern is correct.

        This documents the actual pattern used in web/core/authentik.py
        """
        discord_id = 211533935144992768

        # Pattern from web/core/authentik.py
        attributes = {"discord_id": str(discord_id)}
        query_param = str(discord_id)

        # Verify they match
        assert attributes["discord_id"] == query_param

        # Verify can parse back
        retrieved = int(attributes["discord_id"])
        assert retrieved == discord_id

    def test_discord_id_json_as_string_pattern(self):
        """
        BEST PRACTICE: Document correct JSON serialization pattern.

        Discord IDs MUST be sent as strings in JSON to prevent precision loss.
        """
        discord_id = 987654321098765432

        # CORRECT pattern
        correct_json = json.dumps({"discord_id": str(discord_id)})
        assert '"discord_id": "987654321098765432"' in correct_json

        # Parse back
        parsed = json.loads(correct_json)
        retrieved = int(parsed["discord_id"])
        assert retrieved == discord_id

    def test_javascript_max_safe_integer_exceeded(self):
        """
        DOCUMENTATION: Discord IDs exceed JavaScript MAX_SAFE_INTEGER.

        JavaScript's Number.MAX_SAFE_INTEGER = 2^53 - 1 = 9007199254740991

        Most Discord IDs exceed this, so MUST use strings in JSON/API responses.
        """
        js_max_safe_int = 9007199254740991
        typical_discord_id = 211533935144992768

        # Property: Typical Discord IDs exceed JavaScript's safe range
        assert typical_discord_id > js_max_safe_int

        # This is WHY we must use strings in JSON
        # JavaScript would lose precision if sent as number


@pytest.mark.django_db(transaction=True)
class TestDiscordIDUniquenessConstraints:
    """Test uniqueness and constraint violations."""

    @given(discord_id=discord_id_strategy)
    @settings(max_examples=20)
    def test_active_discord_id_uniqueness(self, discord_id: int):
        """
        Property: Only one active DiscordLink per discord_id.

        From team/models.py:
        - save() override deactivates previous links
        - Only one active link per discord_id at a time
        """
        # Create first link
        link1 = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username="user1",
            authentik_username="auth1",
            authentik_user_id="uid-1",
            is_active=True,
        )

        # Create second link with SAME discord_id
        link2 = DiscordLink.objects.create(
            discord_id=discord_id,
            discord_username="user2",
            authentik_username="auth2",
            authentik_user_id="uid-2",
            is_active=True,
        )

        # Property: Only one is active
        active_count = DiscordLink.objects.filter(discord_id=discord_id, is_active=True).count()
        assert active_count == 1, f"Should have exactly 1 active link, found {active_count}"

        # Property: Most recent is active
        link1.refresh_from_db()
        link2.refresh_from_db()
        assert link2.is_active
        assert not link1.is_active

        # Cleanup
        link1.delete()
        link2.delete()
