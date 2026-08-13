"""Print a secret key line for the environment file.

It writes no file. The install procedure appends the line, so a running key is
never replaced by accident.
"""

import secrets

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Print a new DNSRULES_SECRET_KEY line."

    def handle(self, *args, **options) -> None:
        self.stdout.write(f"DNSRULES_SECRET_KEY={secrets.token_urlsafe(64)}")
