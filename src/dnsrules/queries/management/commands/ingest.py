from argparse import ArgumentParser

from django.conf import settings
from django.core.management.base import BaseCommand

from dnsrules.queries.services import listen


class Command(BaseCommand):
    help = "Listen for the dnstap stream and write the query log."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--host", default=settings.DNSTAP_HOST)
        parser.add_argument("--port", type=int, default=settings.DNSTAP_PORT)

    def handle(self, *args, **options) -> None:
        listen(options["host"], options["port"])
