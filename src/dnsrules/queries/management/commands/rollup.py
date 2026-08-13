from argparse import ArgumentParser

from django.core.management.base import BaseCommand

from dnsrules.queries import rollups


class Command(BaseCommand):
    help = "Roll finished hours and days into the archive, and drop old rows."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--top", type=int, default=rollups.TOP)
        parser.add_argument("--months", type=int, default=rollups.MONTHS)

    def handle(self, *args, **options) -> None:
        hours, days, dropped = rollups.reconcile(
            top=options["top"], months=options["months"]
        )
        self.stdout.write(
            f"Rolled {hours} hourly rows and {days} daily rows. "
            f"Dropped {dropped} rows past {options['months']} months."
        )
