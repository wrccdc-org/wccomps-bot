"""Management command to recalculate final scores."""

from typing import Any

from django.core.management.base import BaseCommand

from scoring.calculator import get_leaderboard, recalculate_all_scores


class Command(BaseCommand):
    help = "Recalculate final scores"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--show-leaderboard",
            action="store_true",
            help="Display leaderboard after recalculation",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        show_leaderboard = options.get("show_leaderboard", False)

        self.stdout.write("Recalculating scores...")

        try:
            recalculate_all_scores()
            self.stdout.write(self.style.SUCCESS("✓ Scores recalculated successfully"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"✗ Failed to recalculate scores: {e}"))
            raise

        if show_leaderboard:
            self.stdout.write("\nLeaderboard:")
            self.stdout.write("-" * 80)
            scores = get_leaderboard()

            if not scores:
                self.stdout.write(self.style.WARNING("No scores found"))
                return

            # Header
            self.stdout.write(
                f"{'Rank':<6} {'Team':<20} {'Services':<10} {'Injects':<10} {'Orange':<10} "
                f"{'Red':<10} {'Incident':<10} {'Total':<10}"
            )
            self.stdout.write("-" * 80)

            # Scores
            for score in scores:
                self.stdout.write(
                    f"{score.rank or '---':<6} {score.team.team_name[:18]:<20} "
                    f"{score.service_points:<10.2f} {score.inject_points:<10.2f} "
                    f"{score.orange_points:<10.2f} {score.red_deductions:<10.2f} "
                    f"{score.incident_recovery_points:<10.2f} {score.total_score:<10.2f}"
                )
