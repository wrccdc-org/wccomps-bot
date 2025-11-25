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

    def test_parse_valid_csv(self, setup_teams: list[Team]) -> None:
        """Test parsing a valid CSV file."""
        csv_content = """team_number,school_name,contact_email,secondary_email,notes
1,University One,contact1@example.edu,alt1@example.edu,Test note 1
2,University Two,contact2@example.edu,,
3,University Three,contact3@example.edu,alt3@example.edu,Test note 3
"""
        csv_file = SimpleUploadedFile("test.csv", csv_content.encode("utf-8"), content_type="text/csv")

        result = parse_csv_file(csv_file)

        assert len(result["rows"]) == 3
        assert len(result["errors"]) == 0
        assert result["rows"][0]["team_number"] == 1
        assert result["rows"][0]["school_name"] == "University One"
        assert result["rows"][0]["contact_email"] == "contact1@example.edu"
        assert result["rows"][0]["secondary_email"] == "alt1@example.edu"
        assert result["rows"][0]["notes"] == "Test note 1"

    def test_parse_csv_missing_required_columns(self) -> None:
        """Test parsing CSV with missing required columns."""
        csv_content = """team_number,school_name
1,University One
"""
        csv_file = SimpleUploadedFile("test.csv", csv_content.encode("utf-8"), content_type="text/csv")

        result = parse_csv_file(csv_file)

        assert len(result["errors"]) > 0
        assert "contact_email" in result["errors"][0]

    def test_parse_csv_invalid_email(self) -> None:
        """Test parsing CSV with invalid email."""
        csv_content = """team_number,school_name,contact_email
1,University One,invalid-email
"""
        csv_file = SimpleUploadedFile("test.csv", csv_content.encode("utf-8"), content_type="text/csv")

        result = parse_csv_file(csv_file)

        assert len(result["errors"]) > 0
        assert "not a valid email" in result["errors"][0]

    def test_parse_csv_invalid_team_number(self) -> None:
        """Test parsing CSV with invalid team number."""
        csv_content = """team_number,school_name,contact_email
abc,University One,contact@example.edu
"""
        csv_file = SimpleUploadedFile("test.csv", csv_content.encode("utf-8"), content_type="text/csv")

        result = parse_csv_file(csv_file)

        assert len(result["errors"]) > 0
        assert "must be a number" in result["errors"][0]

    def test_parse_csv_team_number_out_of_range(self) -> None:
        """Test parsing CSV with team number out of range."""
        csv_content = """team_number,school_name,contact_email
99,University One,contact@example.edu
"""
        csv_file = SimpleUploadedFile("test.csv", csv_content.encode("utf-8"), content_type="text/csv")

        result = parse_csv_file(csv_file)

        assert len(result["errors"]) > 0
        assert "between 1 and 50" in result["errors"][0]

    def test_parse_empty_csv(self) -> None:
        """Test parsing empty CSV."""
        csv_content = ""
        csv_file = SimpleUploadedFile("test.csv", csv_content.encode("utf-8"), content_type="text/csv")

        result = parse_csv_file(csv_file)

        assert len(result["errors"]) > 0


class TestCSVValidation:
    """Test CSV data validation against database."""

    def test_validate_existing_teams(self, setup_teams: list[Team]) -> None:
        """Test validation with existing teams."""
        rows = [
            {
                "team_number": 1,
                "school_name": "University One",
                "contact_email": "contact1@example.edu",
                "secondary_email": "",
                "notes": "",
            },
            {
                "team_number": 2,
                "school_name": "University Two",
                "contact_email": "contact2@example.edu",
                "secondary_email": "",
                "notes": "",
            },
        ]

        result = validate_csv_data(rows)

        assert len(result["errors"]) == 0
        assert len(result["teams_to_create"]) == 2
        assert len(result["teams_to_update"]) == 0

    def test_validate_nonexistent_team(self, setup_teams: list[Team]) -> None:
        """Test validation with non-existent team."""
        rows = [
            {
                "team_number": 99,
                "school_name": "University 99",
                "contact_email": "contact99@example.edu",
                "secondary_email": "",
                "notes": "",
            }
        ]

        result = validate_csv_data(rows)

        assert len(result["errors"]) > 0
        assert "does not exist" in result["errors"][0]

    def test_validate_duplicate_teams(self, setup_teams: list[Team]) -> None:
        """Test validation with duplicate team numbers."""
        rows = [
            {
                "team_number": 1,
                "school_name": "University One",
                "contact_email": "contact1@example.edu",
                "secondary_email": "",
                "notes": "",
            },
            {
                "team_number": 1,
                "school_name": "University One Duplicate",
                "contact_email": "contact1b@example.edu",
                "secondary_email": "",
                "notes": "",
            },
        ]

        result = validate_csv_data(rows)

        assert len(result["errors"]) > 0
        assert "Duplicate" in result["errors"][0]

    def test_validate_update_existing_school_info(self, setup_teams: list[Team]) -> None:
        """Test validation with existing school info (update scenario)."""
        # Create existing school info
        SchoolInfo.objects.create(
            team=setup_teams[0],
            school_name="Old School Name",
            contact_email="old@example.edu",
        )

        rows = [
            {
                "team_number": 1,
                "school_name": "New School Name",
                "contact_email": "new@example.edu",
                "secondary_email": "",
                "notes": "",
            }
        ]

        result = validate_csv_data(rows)

        assert len(result["errors"]) == 0
        assert len(result["teams_to_create"]) == 0
        assert len(result["teams_to_update"]) == 1


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

        result = apply_csv_import(teams_to_create, [], "testuser")

        assert result["created"] == 2
        assert result["updated"] == 0

        # Verify database
        school_info1 = SchoolInfo.objects.get(team=setup_teams[0])
        assert school_info1.school_name == "University One"
        assert school_info1.contact_email == "contact1@example.edu"
        assert school_info1.secondary_email == "alt1@example.edu"
        assert school_info1.notes == "Test note"
        assert school_info1.updated_by == "testuser"

    def test_apply_csv_import_update(self, setup_teams: list[Team], setup_user: User) -> None:
        """Test applying CSV import to update existing school info."""
        # Create existing school info
        existing = SchoolInfo.objects.create(
            team=setup_teams[0],
            school_name="Old School Name",
            contact_email="old@example.edu",
            updated_by="olduser",
        )

        teams_to_update = [
            {
                "_team": setup_teams[0],
                "_existing_school_info": existing,
                "team_number": 1,
                "school_name": "New School Name",
                "contact_email": "new@example.edu",
                "secondary_email": "new-alt@example.edu",
                "notes": "Updated note",
            }
        ]

        result = apply_csv_import([], teams_to_update, "testuser")

        assert result["created"] == 0
        assert result["updated"] == 1

        # Verify database
        existing.refresh_from_db()
        assert existing.school_name == "New School Name"
        assert existing.contact_email == "new@example.edu"
        assert existing.secondary_email == "new-alt@example.edu"
        assert existing.notes == "Updated note"
        assert existing.updated_by == "testuser"

    def test_apply_csv_import_mixed(self, setup_teams: list[Team], setup_user: User) -> None:
        """Test applying CSV import with both creates and updates."""
        # Create existing school info for team 1
        existing = SchoolInfo.objects.create(
            team=setup_teams[0],
            school_name="Old School Name",
            contact_email="old@example.edu",
        )

        teams_to_create = [
            {
                "_team": setup_teams[1],
                "team_number": 2,
                "school_name": "University Two",
                "contact_email": "contact2@example.edu",
                "secondary_email": "",
                "notes": "",
            }
        ]

        teams_to_update = [
            {
                "_team": setup_teams[0],
                "_existing_school_info": existing,
                "team_number": 1,
                "school_name": "New School Name",
                "contact_email": "new@example.edu",
                "secondary_email": "",
                "notes": "",
            }
        ]

        result = apply_csv_import(teams_to_create, teams_to_update, "testuser")

        assert result["created"] == 1
        assert result["updated"] == 1

    def test_apply_csv_import_with_team_name(self, setup_teams: list[Team], setup_user: User) -> None:
        """Test applying CSV import that updates team name."""
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

        result = apply_csv_import(teams_to_create, [], "testuser")

        assert result["created"] == 1

        # Verify team name was updated
        setup_teams[0].refresh_from_db()
        assert setup_teams[0].team_name == "New Team Name"
        assert setup_teams[0].team_name != original_name
