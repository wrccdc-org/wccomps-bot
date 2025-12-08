"""Forms for team management."""

import csv
import io
import random
from typing import TypedDict, cast

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.core.validators import validate_email

from team.models import SchoolInfo, Team


class CSVRowData(TypedDict, total=False):
    school_name: str
    contact_email: str
    secondary_email: str
    notes: str
    team_name: str
    team_number: int
    _team: Team


class CSVParseResult(TypedDict):
    rows: list[CSVRowData]
    errors: list[str]
    warnings: list[str]


class CSVValidationResult(TypedDict):
    teams_to_create: list[CSVRowData]
    errors: list[str]
    warnings: list[str]


class CSVUploadForm(forms.Form):
    """Form for uploading CSV file with team school information."""

    csv_file = forms.FileField(
        label="CSV File",
        help_text=(
            "Upload a CSV file with team school information. "
            "Required columns: school_name, contact_email. "
            "Optional: team_number, secondary_email, notes"
        ),
    )

    def clean_csv_file(self) -> UploadedFile:
        """Validate CSV file format and contents."""
        csv_file = cast(UploadedFile, self.cleaned_data["csv_file"])

        # Check file extension
        if not csv_file.name or not csv_file.name.endswith(".csv"):
            raise ValidationError("File must be a CSV file (.csv)")

        # Check file size (10MB max)
        if csv_file.size and csv_file.size > 10 * 1024 * 1024:
            raise ValidationError("File size must be less than 10MB")

        return csv_file


def parse_csv_file(csv_file: UploadedFile) -> CSVParseResult:
    """
    Parse CSV file and validate contents.

    Returns:
        dict with 'rows' (list of valid data dicts), 'errors' (list of error messages),
        and 'warnings' (list of warning messages)
    """
    rows: list[CSVRowData] = []
    errors: list[str] = []
    warnings: list[str] = []

    try:
        # Read file content
        content = csv_file.read().decode("utf-8")
        csv_file.seek(0)  # Reset file pointer

        # Parse CSV
        reader = csv.DictReader(io.StringIO(content))

        # Validate headers
        required_headers = {"school_name", "contact_email"}
        optional_headers = {"secondary_email", "notes", "team_name"}
        all_headers = required_headers | optional_headers

        if not reader.fieldnames:
            errors.append("CSV file is empty or has no headers")
            return {"rows": rows, "errors": errors, "warnings": warnings}

        headers = set(reader.fieldnames)

        # Check for required headers
        missing_headers = required_headers - headers
        if missing_headers:
            errors.append(f"Missing required columns: {', '.join(sorted(missing_headers))}")
            return {"rows": rows, "errors": errors, "warnings": warnings}

        # Check for unknown headers
        unknown_headers = headers - all_headers
        if unknown_headers:
            warnings.append(f"Unknown columns will be ignored: {', '.join(sorted(unknown_headers))}")

        # Process each row
        for row_num, row in enumerate(reader, start=2):  # Start at 2 (header is row 1)
            row_errors: list[str] = []
            row_data: CSVRowData = {}

            # Validate school_name
            school_name = row.get("school_name", "").strip()
            if not school_name:
                row_errors.append(f"Row {row_num}: school_name is required")
            else:
                row_data["school_name"] = school_name

            # Validate contact_email
            contact_email = row.get("contact_email", "").strip()
            if not contact_email:
                row_errors.append(f"Row {row_num}: contact_email is required")
            else:
                try:
                    validate_email(contact_email)
                    row_data["contact_email"] = contact_email
                except ValidationError:
                    row_errors.append(f"Row {row_num}: contact_email is not a valid email address")

            # Validate secondary_email (optional)
            secondary_email = row.get("secondary_email", "").strip()
            if secondary_email:
                try:
                    validate_email(secondary_email)
                    row_data["secondary_email"] = secondary_email
                except ValidationError:
                    row_errors.append(f"Row {row_num}: secondary_email is not a valid email address")
            else:
                row_data["secondary_email"] = ""

            # Get notes (optional)
            notes = row.get("notes", "").strip()
            row_data["notes"] = notes

            # Get team_name (optional)
            team_name = row.get("team_name", "").strip()
            if team_name:
                row_data["team_name"] = team_name

            # Add row if no errors
            if row_errors:
                errors.extend(row_errors)
            else:
                rows.append(row_data)

        # Check if we have any valid rows
        if not rows and not errors:
            errors.append("CSV file contains no data rows")

    except UnicodeDecodeError:
        errors.append("File encoding error. Please ensure the file is UTF-8 encoded.")
    except Exception as e:
        errors.append(f"Error parsing CSV file: {str(e)}")

    return {"rows": rows, "errors": errors, "warnings": warnings}


def validate_csv_data(rows: list[CSVRowData]) -> CSVValidationResult:
    """
    Validate CSV data against database and assign random team numbers.

    Returns:
        dict with 'teams_to_create', 'errors', 'warnings'
    """
    teams_to_create: list[CSVRowData] = []
    errors: list[str] = []
    warnings: list[str] = []

    # Get teams without school info (available for assignment)
    existing_school_info_team_ids = set(SchoolInfo.objects.values_list("team_id", flat=True))
    available_teams = list(Team.objects.filter(is_active=True).exclude(id__in=existing_school_info_team_ids))

    if len(rows) > len(available_teams):
        errors.append(
            f"Not enough available teams. CSV has {len(rows)} rows but only "
            f"{len(available_teams)} teams without school info."
        )
        return {
            "teams_to_create": teams_to_create,
            "errors": errors,
            "warnings": warnings,
        }

    # Shuffle and assign teams randomly
    random.shuffle(available_teams)

    for i, row in enumerate(rows):
        team = available_teams[i]
        row["_team"] = team
        row["team_number"] = team.team_number
        teams_to_create.append(row)

    return {
        "teams_to_create": teams_to_create,
        "errors": errors,
        "warnings": warnings,
    }


def apply_csv_import(
    teams_to_create: list[CSVRowData],
    updated_by: str,
) -> dict[str, int]:
    """
    Apply CSV import to database.

    Args:
        teams_to_create: List of team data to create SchoolInfo for
        updated_by: Username of person performing the import

    Returns:
        dict with 'created' count
    """
    created = 0

    for row in teams_to_create:
        team = row["_team"]
        SchoolInfo.objects.create(
            team=team,
            school_name=row["school_name"],
            contact_email=row["contact_email"],
            secondary_email=row.get("secondary_email", ""),
            notes=row.get("notes", ""),
            updated_by=updated_by,
        )
        created += 1

        # Update team name if provided
        if "team_name" in row and row["team_name"]:
            team.team_name = row["team_name"]
            team.save()

    return {"created": created}
