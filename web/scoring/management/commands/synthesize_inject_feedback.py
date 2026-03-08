"""Apply synthesized feedback to InjectScore records from a JSON file.

Usage:
    1. Export raw comments:
       python manage.py synthesize_inject_feedback --export > raw_comments.json

    2. Have Claude (or other AI) process raw_comments.json and produce
       feedback.json with the same structure but professional feedback text.

    3. Apply the feedback:
       python manage.py synthesize_inject_feedback --apply feedback.json
"""

import json
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser

from scoring.models import InjectScore


class Command(BaseCommand):
    """Export raw comments or apply synthesized feedback to InjectScore records."""

    help = "Export raw inject comments for synthesis or apply synthesized feedback"

    def add_arguments(self, parser: CommandParser) -> None:
        """Add command arguments."""
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--export",
            action="store_true",
            help="Export raw comments as JSON to stdout",
        )
        group.add_argument(
            "--apply",
            type=str,
            metavar="JSON_FILE",
            help="Apply synthesized feedback from a JSON file",
        )

    def handle(self, *args: str, **options: object) -> None:
        """Execute the command."""
        if options["export"]:
            self._export_comments()
        elif options["apply"]:
            self._apply_feedback(str(options["apply"]))

    def _export_comments(self) -> None:
        """Export all InjectScore records with raw comments as JSON."""
        records = (
            InjectScore.objects.filter(is_approved=True)
            .exclude(inject_id="qualifier-total")
            .exclude(notes="")
            .select_related("team")
            .order_by("inject_id", "team__team_number")
        )

        output: list[dict[str, object]] = [
            {
                "inject_id": rec.inject_id,
                "inject_name": rec.inject_name,
                "team_number": rec.team.team_number,
                "points_awarded": str(rec.points_awarded),
                "max_points": str(rec.max_points) if rec.max_points else None,
                "raw_comments": rec.notes,
                "current_feedback": rec.feedback,
            }
            for rec in records
        ]

        json.dump(output, sys.stdout, indent=2)
        sys.stdout.write("\n")
        self.stderr.write(f"Exported {len(output)} records with comments\n")

    def _apply_feedback(self, json_path: str) -> None:
        """Apply synthesized feedback from a JSON file."""
        path = Path(json_path)
        if not path.exists():
            raise CommandError(f"File not found: {path}")

        with path.open() as f:
            records: list[dict[str, str]] = json.load(f)

        updated = 0
        skipped = 0
        for rec in records:
            feedback = rec.get("feedback", "").strip()
            if not feedback:
                skipped += 1
                continue

            try:
                score = InjectScore.objects.get(
                    inject_id=rec["inject_id"],
                    team__team_number=int(rec["team_number"]),
                )
                score.feedback = feedback
                score.feedback_approved = False  # Reset approval on new feedback
                score.save(update_fields=["feedback", "feedback_approved"])
                updated += 1
            except InjectScore.DoesNotExist:
                self.stderr.write(self.style.WARNING(f"  Not found: {rec['inject_id']} Team {rec['team_number']}"))
                skipped += 1

        self.stdout.write(self.style.SUCCESS(f"Updated {updated} records, skipped {skipped}"))
