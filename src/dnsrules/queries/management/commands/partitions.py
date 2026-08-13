from argparse import ArgumentParser

from django.core.management.base import BaseCommand

from dnsrules.queries import partitions


class Command(BaseCommand):
    help = "Add the coming daily partitions of the query log, and drop old ones."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--ahead", type=int, default=partitions.AHEAD)
        parser.add_argument("--keep", type=int, default=partitions.KEEP)

    def handle(self, *args, **options) -> None:
        added, dropped = partitions.reconcile(
            ahead=options["ahead"], keep=options["keep"]
        )
        self.stdout.write(f"Added {len(added)} partitions, dropped {len(dropped)}.")
        stray = partitions.default_rows()
        if stray:
            self.stdout.write(
                self.style.WARNING(
                    f"{stray} rows sit in the DEFAULT partition. Their day had no "
                    f"partition when they arrived, and it can no longer take one."
                )
            )
