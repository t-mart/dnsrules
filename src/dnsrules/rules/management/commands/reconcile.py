from django.core.management.base import BaseCommand

from dnsrules.rules.services import reconcile


class Command(BaseCommand):
    help = "Raise every zone serial, then tell unbound to fetch the rules again."

    def handle(self, *args, **options) -> None:
        zones = reconcile()
        self.stdout.write(f"Told unbound to fetch {len(zones)}: {', '.join(zones)}")
