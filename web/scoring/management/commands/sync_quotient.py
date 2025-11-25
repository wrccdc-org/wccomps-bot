"""Management command to sync scoring data from Quotient."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError

from competition.models import Competition
from scoring.quotient_sync import sync_quotient_metadata, sync_service_scores


class Command(BaseCommand):
    help = "Sync scoring data from Quotient"

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--metadata-only",
            action="store_true",
            help="Only sync metadata (boxes, services, IPs)",
        )
        parser.add_argument(
            "--scores-only",
            action="store_true",
            help="Only sync service scores",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        metadata_only = options.get("metadata_only", False)
        scores_only = options.get("scores_only", False)

        competition = Competition.objects.first()
        if not competition:
            raise CommandError("No competition found. Create one first.") from None

        self.stdout.write(f"Syncing data for competition: {competition.name}")

        # Sync metadata unless scores-only
        if not scores_only:
            self.stdout.write("Syncing metadata...")
            try:
                metadata = sync_quotient_metadata()
                self.stdout.write(
                    self.style.SUCCESS(f"✓ Metadata synced: {len(metadata.boxes)} boxes, {metadata.team_count} teams")
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Failed to sync metadata: {e}"))
                raise

        # Sync scores unless metadata-only
        if not metadata_only:
            self.stdout.write("Syncing service scores...")
            try:
                result = sync_service_scores()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"✓ Service scores synced: {result['teams_created']} created, {result['teams_updated']} updated"
                    )
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"✗ Failed to sync scores: {e}"))
                raise

        self.stdout.write(self.style.SUCCESS("Sync completed successfully"))
