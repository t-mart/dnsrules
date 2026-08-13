from django.conf import settings
from django.core.management.base import BaseCommand

from dnsrules.rules.services import reconcile


class Command(BaseCommand):
    help = "Render every active rule to the zone file and reload unbound."

    def handle(self, *args, **options) -> None:
        reconcile()
        self.stdout.write(f"Wrote {settings.UNBOUND_ZONE_PATH}.")
