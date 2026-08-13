from django.core.management.base import BaseCommand

from dnsrules.rules.services import reconcile


class Command(BaseCommand):
    help = "Render every active rule to its group's zone file and reload unbound."

    def handle(self, *args, **options) -> None:
        written = reconcile()
        self.stdout.write(f"Wrote {len(written)} zone files: {', '.join(written)}")
