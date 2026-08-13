import logging
from argparse import ArgumentParser

from django.conf import settings
from django.core.management.base import BaseCommand

from dnsrules.queries import partitions
from dnsrules.queries.services import ingest
from dnsrules.unbound import receiver
from dnsrules.unbound.framestream import InvalidStream

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Listen for the dnstap stream and write the query log."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--host", default=settings.DNSTAP_HOST)
        parser.add_argument("--port", type=int, default=settings.DNSTAP_PORT)

    def handle(self, *args, **options) -> None:
        # Insurance. The timer makes the partitions, and a missed run would
        # send every row to the DEFAULT partition.
        partitions.reconcile()
        for chunks in receiver.connections(options["host"], options["port"]):
            try:
                written = ingest(chunks)
            except InvalidStream as problem:
                # The sender died inside a frame. Keep listening for the next
                # connection, because unbound reconnects on its own.
                logger.warning("The dnstap stream ended badly: %s", problem)
                continue
            logger.info("Wrote %d rows from one dnstap connection.", written)
