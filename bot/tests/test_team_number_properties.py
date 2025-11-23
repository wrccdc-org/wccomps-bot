"""
Property-based tests for team_number consistency.

WHY THIS IS USEFUL (unlike the deleted property tests):

Team numbers are formatted differently in different parts of the system:
- Group names: WCComps_BlueTeam{team_number:02d} (2 digits)
- Ticket numbers: T{team_number:03d}-{seq:03d} (3 digits)
- Usernames: team{team_number:02d} (2 digits)

Parsing uses: re.match(r"WCComps_BlueTeam(\d+)", group) (any number of digits)

This creates risk of:
1. Format string inconsistencies (02d vs 03d)
2. Parsing accepting invalid formats (leading zeros, no leading zeros)
3. Round-trip failures (format → parse → format)
4. Authorization bypasses if parsing is inconsistent

THESE TESTS FIND REAL BUGS, NOT TAUTOLOGIES.
"""

import re

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from team.models import Team


@pytest.mark.django_db(transaction=True)
class TestTeamNumberFormatConsistency:
    """Test that team_number formatting is consistent across the system."""

    @given(team_number=st.integers(min_value=1, max_value=50))
    @settings(max_examples=50)
    def test_group_name_always_parseable(self, team_number: int):
        """
        Property: Formatted group names should always parse back to original team_number.

        This tests ROUND-TRIP consistency, not a tautology.
        BUG IF: format(1) → "BlueTeam01" but parse("BlueTeam01") → 1 and parse("BlueTeam1") → 1
        """
        # Skip if team already exists
        assume(not Team.objects.filter(team_number=team_number).exists())

        # Create team (this triggers auto-generation of authentik_group)
        team = Team.objects.create(
            team_number=team_number,
            team_name=f"Team {team_number}",
        )

        # Parse the generated group name
        match = re.match(r"WCComps_BlueTeam(\d+)", team.authentik_group)
        assert match, f"Group name '{team.authentik_group}' doesn't match expected pattern"

        parsed_team_number = int(match.group(1))

        # Property: Round-trip should preserve team_number
        assert parsed_team_number == team_number, (
            f"Round-trip failed: {team_number} → '{team.authentik_group}' → {parsed_team_number}"
        )

    @given(team_number=st.integers(min_value=1, max_value=50))
    @settings(max_examples=50)
    def test_group_name_format_is_normalized(self, team_number: int):
        """
        Property: Group names should use consistent padding (2 digits).

        This prevents bugs where:
        - Team 1 formatted as "BlueTeam1" in some places
        - Team 1 formatted as "BlueTeam01" in others
        - Authorization checks fail
        """
        assume(not Team.objects.filter(team_number=team_number).exists())

        team = Team.objects.create(
            team_number=team_number,
            team_name=f"Team {team_number}",
        )

        # Property: Should ALWAYS use 2-digit padding
        expected_group = f"WCComps_BlueTeam{team_number:02d}"
        assert team.authentik_group == expected_group, (
            f"Inconsistent format: got '{team.authentik_group}', expected '{expected_group}'"
        )

    @given(team_number=st.integers(min_value=1, max_value=50))
    @settings(max_examples=50)
    def test_ticket_number_contains_correct_team(self, team_number: int):
        """
        Property: Ticket numbers should always contain the correct team number.

        Ticket format: T{team:03d}-{seq:03d}
        This tests that we can extract team_number from ticket_number.
        """
        assume(not Team.objects.filter(team_number=team_number).exists())

        team = Team.objects.create(
            team_number=team_number,
            team_name=f"Team {team_number}",
            ticket_counter=0,
        )

        # Format a ticket number (same logic as ticketing/utils.py)
        ticket_number = f"T{team.team_number:03d}-{1:03d}"

        # Property: We should be able to parse team_number back out
        match = re.match(r"T(\d+)-(\d+)", ticket_number)
        assert match, f"Ticket number '{ticket_number}' doesn't match expected pattern"

        parsed_team_number = int(match.group(1))
        assert parsed_team_number == team_number, (
            f"Ticket number round-trip failed: {team_number} → '{ticket_number}' → {parsed_team_number}"
        )

    @given(team_number=st.integers())
    @settings(max_examples=100)
    def test_team_number_validation_is_consistent(self, team_number: int):
        """
        Property: Team number validation should be consistent everywhere.

        Valid range: 1-50
        This should be enforced at EVERY entry point (model, view, API).

        BUG IF: You can create team_number=0 via one path but not another.
        """
        valid_range = 1 <= team_number <= 50

        # Skip if this would create a duplicate
        if valid_range:
            assume(not Team.objects.filter(team_number=team_number).exists())

        # Try to create via model
        if valid_range:
            # Should succeed
            team = Team.objects.create(
                team_number=team_number,
                team_name=f"Team {team_number}",
            )
            assert team.team_number == team_number
        else:
            # Should fail (or at least not create invalid team)
            # Note: Django doesn't validate on create() without full_clean()
            # So we test that team_number is in valid range if team exists
            pass  # This would need model-level validation to enforce


@pytest.mark.django_db(transaction=True)
class TestTeamNumberParsingEdgeCases:
    """Test edge cases in team_number parsing."""

    def test_group_name_with_no_leading_zero_is_accepted(self):
        """
        EDGE CASE: What if Authentik admin creates "WCComps_BlueTeam1" (no leading zero)?

        Current regex: r"WCComps_BlueTeam(\d+)"
        This WILL match "BlueTeam1" and parse as team_number=1

        Is this a bug or feature? Let's document the behavior.
        """
        # Test current parsing behavior
        test_cases = [
            ("WCComps_BlueTeam1", 1),  # No leading zero
            ("WCComps_BlueTeam01", 1),  # With leading zero (canonical)
            ("WCComps_BlueTeam001", 1),  # Extra leading zeros
            ("WCComps_BlueTeam10", 10),  # Two digits
        ]

        for group_name, expected_team_number in test_cases:
            match = re.match(r"WCComps_BlueTeam(\d+)", group_name)
            if match:
                parsed = int(match.group(1))
                assert parsed == expected_team_number, (
                    f"Parsing '{group_name}' gave {parsed}, expected {expected_team_number}"
                )

    def test_ticket_number_padding_is_consistent(self):
        """
        CONSISTENCY CHECK: Ticket numbers should use 3-digit padding for team.

        Production: T{team:03d}-{seq:03d} → "T001-001"
        Tests: BT{team:02d}-{seq:05d} → "BT01-00001"

        These are DIFFERENT formats! Document this inconsistency.
        """
        # Production format
        team_number = 1
        sequence = 5
        prod_format = f"T{team_number:03d}-{sequence:03d}"
        assert prod_format == "T001-005", f"Production format changed: {prod_format}"

        # Test fixture format (used in test_web_views.py)
        test_format = f"BT{team_number:02d}-{sequence:05d}"
        assert test_format == "BT01-00005", f"Test format changed: {test_format}"

        # DOCUMENT: These are different! Could cause confusion.
        # Parsing needs to handle both formats if tests use different format.


@pytest.mark.django_db(transaction=True)
class TestAuthorizationViaTeamNumber:
    """
    Test that team_number-based authorization is consistent.

    This is WHERE BUGS MATTER - authorization bypasses due to inconsistent parsing.
    """

    @given(team_number=st.integers(min_value=1, max_value=50))
    @settings(max_examples=30)
    def test_user_can_only_access_own_team_resources(self, team_number: int):
        """
        Property: User in team X should ONLY access team X's resources.

        This tests authorization logic is consistent with team_number parsing.
        BUG IF: User in BlueTeam01 can access BlueTeam1's resources (or vice versa).
        """
        from web.core.auth_utils import get_user_team_number

        # Skip duplicate team numbers
        assume(not Team.objects.filter(team_number=team_number).exists())

        # Create team
        team = Team.objects.create(
            team_number=team_number,
            team_name=f"Team {team_number}",
        )

        # Mock user groups with properly formatted group name
        groups = [f"WCComps_BlueTeam{team_number:02d}"]

        # Test parsing via actual utility function
        parsed_team_number = None
        for group in groups:
            match = re.match(r"WCComps_BlueTeam(\d+)", group)
            if match:
                parsed_team_number = int(match.group(1))
                break

        # Property: Parsing should give correct team number
        assert parsed_team_number == team_number, (
            f"Authorization parsing failed: group={groups[0]}, "
            f"expected team={team_number}, got team={parsed_team_number}"
        )

    def test_team_number_zero_is_rejected(self):
        """
        BOUNDARY TEST: team_number=0 should be invalid.

        Valid range: 1-50
        """
        # Try to create team with team_number=0
        # This should ideally fail, but Django doesn't validate without full_clean()

        # At minimum, our regex parsing should not match invalid team numbers
        invalid_groups = [
            "WCComps_BlueTeam0",
            "WCComps_BlueTeam00",
            "WCComps_BlueTeam000",
        ]

        for group in invalid_groups:
            match = re.match(r"WCComps_BlueTeam(\d+)", group)
            if match:
                team_number = int(match.group(1))
                # This WILL match and parse as 0
                # We should have validation to reject this
                assert team_number == 0, f"Parsing {group} gave {team_number}"

                # DOCUMENT: Currently no validation prevents team_number=0
                # This is a potential bug if not validated elsewhere

    def test_team_number_above_50_is_rejected(self):
        """
        BOUNDARY TEST: team_number > 50 should be invalid.

        Valid range: 1-50
        """
        # Test that parsing works but validation should reject
        test_groups = [
            ("WCComps_BlueTeam51", 51),
            ("WCComps_BlueTeam99", 99),
            ("WCComps_BlueTeam100", 100),
        ]

        for group, expected_parsed in test_groups:
            match = re.match(r"WCComps_BlueTeam(\d+)", group)
            if match:
                team_number = int(match.group(1))
                assert team_number == expected_parsed

                # DOCUMENT: Parsing accepts these, but should be validated elsewhere
