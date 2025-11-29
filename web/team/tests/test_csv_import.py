"""Tests for CSV import functionality."""

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from team.forms import apply_csv_import, parse_csv_file, validate_csv_data
from team.models import SchoolInfo, Team

pytestmark = pytest.mark.django_db


@pytest.fixture
def setup_teams() -> list[Team]:
    """Create test teams."""
    teams = []
    for i in range(1, 6):
        team = Team.objects.create(
            team_name=f"Team {i}",
            team_number=i,
            max_members=10,
            is_active=True,
        )
        teams.append(team)
    return teams


@pytest.fixture
def setup_user() -> User:
    """Create test user."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )


class TestCSVParsing:
    """Test CSV parsing and validation."""

    def test_parse_valid_csv(self) -> None:
        """Test parsing a valid CSV file."""
        csv_content = """school_name,contact_email,secondary_email,notes
University One,contact1@example.edu,alt1@example.edu,Test note 1
University Two,contact2@example.edu,,
University Three,contact3@example.edu,alt3@example.edu,Test note 3
"""
        csv_file = SimpleUploadedFile("test.csv", csv_content.encode("utf-8"), content_type="text/csv")

        result = parse_csv_file(csv_file)

        assert len(result["rows"]) == 3
        assert len(result["errors"]) == 0
        assert result["rows"][0]["school_name"] == "University One"
        assert result["rows"][0]["contact_email"] == "contact1@example.edu"
        assert result["rows"][0]["secondary_email"] == "alt1@example.edu"
        assert result["rows"][0]["notes"] == "Test note 1"

    def test_parse_csv_missing_required_columns(self) -> None:
        """Test parsing CSV with missing required columns."""
        csv_content = """school_name
University One
"""
        csv_file = SimpleUploadedFile("test.csv", csv_content.encode("utf-8"), content_type="text/csv")

        result = parse_csv_file(csv_file)

        assert len(result["errors"]) > 0
        assert "contact_email" in result["errors"][0]

    def test_parse_csv_invalid_email(self) -> None:
        """Test parsing CSV with invalid email."""
        csv_content = """school_name,contact_email
University One,invalid-email
"""
        csv_file = SimpleUploadedFile("test.csv", csv_content.encode("utf-8"), content_type="text/csv")

        result = parse_csv_file(csv_file)

        assert len(result["errors"]) > 0
        assert "not a valid email" in result["errors"][0]

    def test_parse_empty_csv(self) -> None:
        """Test parsing empty CSV."""
        csv_content = ""
        csv_file = SimpleUploadedFile("test.csv", csv_content.encode("utf-8"), content_type="text/csv")

        result = parse_csv_file(csv_file)

        assert len(result["errors"]) > 0

    def test_parse_csv_with_team_name(self) -> None:
        """Test parsing CSV with optional team_name column."""
        csv_content = """school_name,contact_email,team_name
University One,contact1@example.edu,Blue Team
"""
        csv_file = SimpleUploadedFile("test.csv", csv_content.encode("utf-8"), content_type="text/csv")

        result = parse_csv_file(csv_file)

        assert len(result["rows"]) == 1
        assert len(result["errors"]) == 0
        assert result["rows"][0]["team_name"] == "Blue Team"


class TestCSVValidation:
    """Test CSV data validation against database."""

    def test_validate_assigns_random_teams(self, setup_teams: list[Team]) -> None:
        """Test validation assigns teams randomly."""
        rows = [
            {
                "school_name": "University One",
                "contact_email": "contact1@example.edu",
                "secondary_email": "",
                "notes": "",
            },
            {
                "school_name": "University Two",
                "contact_email": "contact2@example.edu",
                "secondary_email": "",
                "notes": "",
            },
        ]

        result = validate_csv_data(rows)

        assert len(result["errors"]) == 0
        assert len(result["teams_to_create"]) == 2
        # Each row should have a team assigned
        for row in result["teams_to_create"]:
            assert "_team" in row
            assert "team_number" in row

    def test_validate_not_enough_teams(self, setup_teams: list[Team]) -> None:
        """Test validation fails when more rows than available teams."""
        # Create school info for all but one team
        for team in setup_teams[:-1]:
            SchoolInfo.objects.create(
                team=team,
                school_name=f"School for {team.team_name}",
                contact_email=f"contact{team.team_number}@example.edu",
            )

        # Try to import 2 rows when only 1 team is available
        rows = [
            {
                "school_name": "University One",
                "contact_email": "contact1@example.edu",
                "secondary_email": "",
                "notes": "",
            },
            {
                "school_name": "University Two",
                "contact_email": "contact2@example.edu",
                "secondary_email": "",
                "notes": "",
            },
        ]

        result = validate_csv_data(rows)

        assert len(result["errors"]) > 0
        assert "Not enough available teams" in result["errors"][0]

    def test_validate_excludes_teams_with_school_info(self, setup_teams: list[Team]) -> None:
        """Test validation only assigns teams without existing school info."""
        # Create school info for first team
        SchoolInfo.objects.create(
            team=setup_teams[0],
            school_name="Existing School",
            contact_email="existing@example.edu",
        )

        rows = [
            {
                "school_name": "New School",
                "contact_email": "new@example.edu",
                "secondary_email": "",
                "notes": "",
            },
        ]

        result = validate_csv_data(rows)

        assert len(result["errors"]) == 0
        assert len(result["teams_to_create"]) == 1
        # Assigned team should not be the one with existing school info
        assert result["teams_to_create"][0]["_team"].id != setup_teams[0].id


class TestCSVImport:
    """Test CSV import application."""

    def test_apply_csv_import_create(self, setup_teams: list[Team], setup_user: User) -> None:
        """Test applying CSV import to create new school info."""
        teams_to_create = [
            {
                "_team": setup_teams[0],
                "team_number": 1,
                "school_name": "University One",
                "contact_email": "contact1@example.edu",
                "secondary_email": "alt1@example.edu",
                "notes": "Test note",
            },
            {
                "_team": setup_teams[1],
                "team_number": 2,
                "school_name": "University Two",
                "contact_email": "contact2@example.edu",
                "secondary_email": "",
                "notes": "",
            },
        ]

        result = apply_csv_import(teams_to_create, "testuser")

        assert result["created"] == 2

        # Verify database
        school_info1 = SchoolInfo.objects.get(team=setup_teams[0])
        assert school_info1.school_name == "University One"
        assert school_info1.contact_email == "contact1@example.edu"
        assert school_info1.secondary_email == "alt1@example.edu"
        assert school_info1.notes == "Test note"
        assert school_info1.updated_by == "testuser"

    def test_apply_csv_import_with_team_name(self, setup_teams: list[Team], setup_user: User) -> None:
        """Test applying CSV import that sets team name."""
        original_name = setup_teams[0].team_name

        teams_to_create = [
            {
                "_team": setup_teams[0],
                "team_number": 1,
                "school_name": "University One",
                "contact_email": "contact1@example.edu",
                "secondary_email": "",
                "notes": "",
                "team_name": "New Team Name",
            }
        ]

        result = apply_csv_import(teams_to_create, "testuser")

        assert result["created"] == 1

        # Verify team name was set
        setup_teams[0].refresh_from_db()
        assert setup_teams[0].team_name == "New Team Name"
        assert setup_teams[0].team_name != original_name
