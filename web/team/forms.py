"""Forms for team management."""

import csv
import io
from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from team.models import SchoolInfo, Team


class CSVUploadForm(forms.Form):
    """Form for uploading CSV file with team school information."""

    csv_file = forms.FileField(
        label="CSV File",
        help_text=(
            "Upload a CSV file with team school information. "
            "Required columns: team_number, school_name, contact_email. "
            "Optional: secondary_email, notes"
        ),
    )

    def clean_csv_file(self) -> Any:
        """Validate CSV file format and contents."""
        csv_file = self.cleaned_data["csv_file"]

        # Check file extension
        if not csv_file.name.endswith(".csv"):
            raise ValidationError("File must be a CSV file (.csv)")

        # Check file size (10MB max)
        if csv_file.size > 10 * 1024 * 1024:
            raise ValidationError("File size must be less than 10MB")

        return csv_file


def parse_csv_file(csv_file: Any) -> dict[str, Any]:
    """
    Parse CSV file and validate contents.

    Returns:
        dict with 'rows' (list of valid data dicts), 'errors' (list of error messages),
        and 'warnings' (list of warning messages)
    """
    rows = []
    errors = []
    warnings = []

    try:
        # Read file content
        content = csv_file.read().decode("utf-8")
        csv_file.seek(0)  # Reset file pointer

        # Parse CSV
        reader = csv.DictReader(io.StringIO(content))

        # Validate headers
        required_headers = {"team_number", "school_name", "contact_email"}
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
            row_errors = []
            row_data = {}

            # Validate team_number
            team_number_str = row.get("team_number", "").strip()
            if not team_number_str:
                row_errors.append(f"Row {row_num}: team_number is required")
            else:
                try:
                    team_number = int(team_number_str)
                    if team_number < 1 or team_number > 50:
                        row_errors.append(f"Row {row_num}: team_number must be between 1 and 50")
                    else:
                        row_data["team_number"] = team_number
                except ValueError:
                    row_errors.append(f"Row {row_num}: team_number must be a number")

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


def validate_csv_data(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Validate CSV data against database.

    Checks:
    - Team numbers exist in database
    - Duplicate team numbers in CSV
    - Which teams will be created vs updated

    Returns:
        dict with 'teams_to_create', 'teams_to_update', 'errors', 'warnings'
    """
    teams_to_create = []
    teams_to_update = []
    errors = []
    warnings = []

    # Check for duplicate team numbers in CSV
    team_numbers = [row["team_number"] for row in rows]
    duplicates = {num for num in team_numbers if team_numbers.count(num) > 1}
    if duplicates:
        errors.append(f"Duplicate team numbers in CSV: {', '.join(map(str, sorted(duplicates)))}")
        return {
            "teams_to_create": teams_to_create,
            "teams_to_update": teams_to_update,
            "errors": errors,
            "warnings": warnings,
        }

    # Get all teams from database
    existing_teams = {team.team_number: team for team in Team.objects.filter(is_active=True)}
    existing_school_infos = {si.team.team_number: si for si in SchoolInfo.objects.select_related("team").all()}

    for row in rows:
        team_number = row["team_number"]

        # Check if team exists
        if team_number not in existing_teams:
            errors.append(f"Team {team_number} does not exist in the database")
            continue

        team = existing_teams[team_number]

        # Check if we're creating or updating
        if team_number in existing_school_infos:
            school_info = existing_school_infos[team_number]
            row["_existing_school_info"] = school_info
            row["_team"] = team
            teams_to_update.append(row)
        else:
            row["_team"] = team
            teams_to_create.append(row)

    return {
        "teams_to_create": teams_to_create,
        "teams_to_update": teams_to_update,
        "errors": errors,
        "warnings": warnings,
    }


def apply_csv_import(
    teams_to_create: list[dict[str, Any]],
    teams_to_update: list[dict[str, Any]],
    updated_by: str,
) -> dict[str, int]:
    """
    Apply CSV import to database.

    Args:
        teams_to_create: List of team data to create SchoolInfo for
        teams_to_update: List of team data to update SchoolInfo for
        updated_by: Username of person performing the import

    Returns:
        dict with 'created' and 'updated' counts
    """
    created = 0
    updated = 0

    # Create new school info records
    for row in teams_to_create:
        team = row["_team"]
        school_info = SchoolInfo.objects.create(
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

    # Update existing school info records
    for row in teams_to_update:
        school_info = row["_existing_school_info"]
        team = row["_team"]

        school_info.school_name = row["school_name"]
        school_info.contact_email = row["contact_email"]
        school_info.secondary_email = row.get("secondary_email", "")
        school_info.notes = row.get("notes", "")
        school_info.updated_by = updated_by
        school_info.save()
        updated += 1

        # Update team name if provided
        if "team_name" in row and row["team_name"]:
            team.team_name = row["team_name"]
            team.save()

    return {"created": created, "updated": updated}
