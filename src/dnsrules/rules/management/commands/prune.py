from django.core.management.base import BaseCommand

from dnsrules.rules.services import prune


class Command(BaseCommand):
    help = "Delete expired rules, then tell unbound to fetch the rules again."

    def handle(self, *args, **options) -> None:
        count = prune()
        self.stdout.write(f"Deleted {count} expired rules.")
