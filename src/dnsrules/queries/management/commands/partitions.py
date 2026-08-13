from argparse import ArgumentParser

from django.conf import settings
from django.core.management.base import BaseCommand

from dnsrules.queries import partitions


class Command(BaseCommand):
    help = "Add the coming daily partitions of the query log, and drop old ones."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--ahead", type=int, default=partitions.AHEAD)
        parser.add_argument("--keep", type=int, default=partitions.KEEP)
        parser.add_argument("--max-bytes", type=int, default=settings.LOG_MAX_BYTES)

    def handle(self, *args, **options) -> None:
        added, dropped = partitions.reconcile(
            ahead=options["ahead"], keep=options["keep"]
        )
        self.stdout.write(f"Added {len(added)} partitions, dropped {len(dropped)}.")

        over = partitions.enforce_cap(options["max_bytes"])
        used = partitions.size() / 1024**3
        self.stdout.write(f"The query log holds {used:.2f} GiB.")
        if over:
            self.stdout.write(
                self.style.WARNING(
                    f"{len(over)} days went early, from {over[0]} to {over[-1]}, "
                    f"because the log passed its cap. Retention by age is the "
                    f"plan, so lower --keep or raise DNSRULES_LOG_MAX_BYTES."
                )
            )
        stray = partitions.default_rows()
        if stray:
            self.stdout.write(
                self.style.WARNING(
                    f"{stray} rows sit in the DEFAULT partition. Their day had no "
                    f"partition when they arrived, and it can no longer take one."
                )
            )
