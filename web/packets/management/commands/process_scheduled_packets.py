"""Management command to process scheduled packet distributions."""

from django.core.management.base import BaseCommand

from packets.services import ScheduledPacketDistributor


class Command(BaseCommand):
    help = "Process scheduled packet distributions"

    def handle(self, *args, **options):
        """Process all scheduled packets ready for distribution."""
        self.stdout.write("Processing scheduled packets...")

        distributor = ScheduledPacketDistributor()
        result = distributor.process_scheduled_packets()

        if result["processed"] > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Processed {result['processed']} packet(s), {result['failed']} failed"
                )
            )
        else:
            self.stdout.write("No scheduled packets to process")
