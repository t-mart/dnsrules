from django.core.management.base import BaseCommand

from dnsrules.rules.services import prune


class Command(BaseCommand):
    help = "Delete expired rules, then rewrite the zone file and reload unbound."

    def handle(self, *args, **options) -> None:
        count = prune()
        self.stdout.write(f"Deleted {count} expired rules.")
