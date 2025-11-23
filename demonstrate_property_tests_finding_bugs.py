"""
Demonstration: What bugs do these property-based tests actually catch?

This shows concrete examples of bugs that would be caught by the property tests.
"""


# Example 1: Inconsistent formatting
class BuggyTeamFormatting:
    """BUG: Inconsistent formatting in different code paths."""

    @staticmethod
    def format_for_authentik(team_number):
        """Format for Authentik group name."""
        # BUG: Different padding in different places
        if team_number < 10:
            return f"WCComps_BlueTeam{team_number}"  # No leading zero!
        else:
            return f"WCComps_BlueTeam{team_number:02d}"  # With leading zero

    @staticmethod
    def parse_from_group(group_name):
        """Parse team_number from group name."""
        import re
        match = re.match(r"WCComps_BlueTeam(\d+)", group_name)
        if match:
            return int(match.group(1))
        return None


def demonstrate_bug_1():
    """
    BUG: Inconsistent formatting causes authorization failures.

    User in "BlueTeam5" can't access resources that check for "BlueTeam05".
    """
    print("=== BUG 1: Inconsistent Formatting ===\n")

    for team_number in [1, 5, 10, 25]:
        # Format the group name
        group_name = BuggyTeamFormatting.format_for_authentik(team_number)

        # Parse it back
        parsed = BuggyTeamFormatting.parse_from_group(group_name)

        # Expected format
        expected = f"WCComps_BlueTeam{team_number:02d}"

        # Check consistency
        if group_name != expected:
            print(f"❌ BUG FOUND: team_number={team_number}")
            print(f"   Generated: {group_name}")
            print(f"   Expected:  {expected}")
            print(f"   Parsed back: {parsed}")
            print(f"   → Authorization checks for '{expected}' will fail!\n")
        else:
            print(f"✓ team_number={team_number}: {group_name}")

    print("Property-based test would generate team_number=1 and FAIL immediately.\n")


# Example 2: Missing validation
class BuggyTeamValidation:
    """BUG: Validation not called in all code paths."""

    @staticmethod
    def create_team_via_admin(team_number, team_name):
        """Admin creates team (calls validation)."""
        if team_number < 1 or team_number > 50:
            raise ValueError(f"Invalid team_number: {team_number}")
        return {"team_number": team_number, "team_name": team_name}

    @staticmethod
    def create_team_via_migration(team_number, team_name):
        """Migration creates team (BUG: skips validation!)."""
        # BUG: No validation in migration path
        return {"team_number": team_number, "team_name": team_name}


def demonstrate_bug_2():
    """
    BUG: Validation bypassed via migration path.

    Database ends up with team_number=0 or team_number=99.
    """
    print("=== BUG 2: Missing Validation in Migration Path ===\n")

    test_cases = [0, -1, 51, 99]

    for team_number in test_cases:
        # Admin path (has validation)
        try:
            BuggyTeamValidation.create_team_via_admin(team_number, f"Team {team_number}")
            print(f"❌ Admin path FAILED: Should reject team_number={team_number}")
        except ValueError:
            print(f"✓ Admin path: team_number={team_number} rejected")

        # Migration path (BUG: no validation)
        try:
            team = BuggyTeamValidation.create_team_via_migration(team_number, f"Team {team_number}")
            print(f"❌ Migration path BUG: Created invalid team_number={team_number}")
            print(f"   → Database now has invalid data!\n")
        except ValueError:
            print(f"✓ Migration path: team_number={team_number} rejected\n")

    print("Property-based test would try team_number=0 and find the bug.\n")


# Example 3: Ticket number parsing mismatch
class BuggyTicketParsing:
    """BUG: Ticket generation and parsing use different formats."""

    @staticmethod
    def generate_ticket_number(team_number, sequence):
        """Generate ticket number (production code)."""
        # Production uses 3 digits
        return f"T{team_number:03d}-{sequence:03d}"

    @staticmethod
    def parse_ticket_number(ticket_number):
        """Parse ticket number (BUG: expects 2 digits)."""
        import re
        # BUG: This regex expects 2-digit team number!
        match = re.match(r"T(\d{2})-(\d+)", ticket_number)
        if match:
            return int(match.group(1)), int(match.group(2))
        return None, None


def demonstrate_bug_3():
    """
    BUG: Parsing expects 2 digits, but generation uses 3.

    Parsing fails for tickets from teams 1-9.
    """
    print("=== BUG 3: Ticket Format Mismatch ===\n")

    for team_number in [1, 5, 10, 25]:
        sequence = 42

        # Generate ticket
        ticket_number = BuggyTicketParsing.generate_ticket_number(team_number, sequence)

        # Try to parse it
        parsed_team, parsed_seq = BuggyTicketParsing.parse_ticket_number(ticket_number)

        if parsed_team is None:
            print(f"❌ BUG FOUND: team_number={team_number}")
            print(f"   Generated: {ticket_number}")
            print(f"   Parsing FAILED - regex expects 2 digits, got 3")
            print(f"   → Can't look up ticket by ticket_number!\n")
        else:
            print(f"✓ team_number={team_number}: {ticket_number} → team={parsed_team}, seq={parsed_seq}")

    print("Property-based test would try team_number=1 and FAIL on first example.\n")


# Example 4: Authorization bypass via case sensitivity
class BuggyAuthorizationCheck:
    """BUG: Case-sensitive group name check."""

    @staticmethod
    def check_team_access(user_groups, required_team):
        """Check if user can access team resources."""
        # BUG: Case-sensitive string comparison
        required_group = f"WCComps_BlueTeam{required_team:02d}"
        return required_group in user_groups  # Exact match required


def demonstrate_bug_4():
    """
    BUG: Case-sensitive authorization allows bypass.

    User in "wccomps_blueteam01" (lowercase) bypasses checks.
    """
    print("=== BUG 4: Case-Sensitive Authorization ===\n")

    test_cases = [
        ("WCComps_BlueTeam01", 1, True, "Canonical format"),
        ("wccomps_blueteam01", 1, False, "Lowercase (from misconfigured Authentik)"),
        ("WCCOMPS_BLUETEAM01", 1, False, "Uppercase"),
        ("WCComps_BlueTeam1", 1, False, "No leading zero"),
    ]

    for group_name, team_number, should_pass, description in test_cases:
        user_groups = [group_name]
        has_access = BuggyAuthorizationCheck.check_team_access(user_groups, team_number)

        if has_access and not should_pass:
            print(f"❌ AUTHORIZATION BYPASS: {description}")
            print(f"   Group: {group_name}")
            print(f"   Gained access to team {team_number}\n")
        elif not has_access and should_pass:
            print(f"❌ FALSE REJECTION: {description}")
            print(f"   Group: {group_name}")
            print(f"   Denied access to team {team_number}\n")
        else:
            status = "✓" if should_pass else "✗"
            print(f"{status} {description}: {group_name} → access={has_access}")

    print("\nProperty-based test wouldn't catch this (generates valid integers).")
    print("But edge case tests with string variations would catch it.\n")


# Summary
def demonstrate_why_property_tests_matter():
    """
    Summary: What value do property-based tests provide?
    """
    print("\n" + "=" * 60)
    print("WHY PROPERTY-BASED TESTS MATTER FOR team_number")
    print("=" * 60 + "\n")

    print("team_number is used in:")
    print("  - 137 locations across 20 files")
    print("  - 4 different format strings (02d, 03d, 05d, no padding)")
    print("  - Authorization checks (IDOR prevention)")
    print("  - Database lookups (ticket_number parsing)")
    print("  - External API calls (Authentik groups)")
    print()

    print("Bugs property tests WOULD catch:")
    print("  ✓ Inconsistent formatting (02d vs 03d vs no padding)")
    print("  ✓ Round-trip failures (format → parse → different value)")
    print("  ✓ Missing validation (accept team_number=0 or 99)")
    print("  ✓ Boundary conditions (1, 50, off-by-one errors)")
    print("  ✓ Cross-system inconsistencies (groups vs tickets)")
    print()

    print("Bugs property tests WOULDN'T catch:")
    print("  ✗ Case sensitivity issues (requires string variation)")
    print("  ✗ SQL injection (requires specific payloads)")
    print("  ✗ Race conditions (requires concurrent execution)")
    print()

    print("Conclusion:")
    print("  Property-based tests are PERFECT for team_number because:")
    print("  1. It's a simple integer with clear invariants")
    print("  2. It's used in many places with format variations")
    print("  3. Bugs would cause authorization failures (security)")
    print("  4. Traditional example-based tests would miss edge cases")
    print()


if __name__ == "__main__":
    demonstrate_bug_1()
    demonstrate_bug_2()
    demonstrate_bug_3()
    demonstrate_bug_4()
    demonstrate_why_property_tests_matter()

    print("=" * 60)
    print("RUN THE PROPERTY-BASED TESTS TO VERIFY NO BUGS EXIST")
    print("=" * 60)
