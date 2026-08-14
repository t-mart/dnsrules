"""Run the recurring jobs.

`serve` runs this in a thread, so a deployment needs no second process. Run it
on its own during development, next to `runserver`.
"""

import signal
import threading

from django.core.management.base import BaseCommand

from dnsrules.core import jobs


class Command(BaseCommand):
    help = "Run the recurring jobs until stopped."

    def handle(self, *args, **options) -> None:
        stop = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        self.stdout.write(f"Running {', '.join(jobs.SCHEDULE)}. Stop with Ctrl-C.")
        jobs.worker(stop)
