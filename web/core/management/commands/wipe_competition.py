"""Wipe all competition data (nuclear option)."""

from django.core.management.base import BaseCommand, CommandParser

from core.competition_utils import wipe_competition_data


class Command(BaseCommand):
    help = "Wipe all competition data (DESTRUCTIVE)"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--confirm",
            action="store_true",
            help="Confirm that you want to delete all data",
        )

    def handle(self, *args: str, **options: object) -> None:
        if not options["confirm"]:
            self.stdout.write(
                self.style.ERROR("This command will DELETE ALL competition data!\nRun with --confirm to proceed.")
            )
            return

        self.stdout.write(self.style.WARNING("Wiping all competition data..."))

        counts = wipe_competition_data()

        self.stdout.write(self.style.SUCCESS("\nDeleted:"))
        for model, count in counts.items():
            if count > 0:
                self.stdout.write(f"  {model}: {count}")

        self.stdout.write(self.style.SUCCESS("\nAll competition data wiped!"))
