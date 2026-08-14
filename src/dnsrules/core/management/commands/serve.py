"""Run the whole thing in one process.

gunicorn goes through its Python API, not its console script, so the install
carries one entry point.

One worker, and the background threads start inside it. gunicorn forks its
workers, and a database connection opened before that fork would be shared by
two processes, which corrupts the protocol. `post_worker_init` runs after the
fork, so nothing is inherited. At three queries a second and one reader, one
worker with threads has room to spare.

Errors go to stderr. There is no access log: one line for each restart is worth
more than a busy log that buries it.
"""

import threading
from argparse import ArgumentParser

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.core.wsgi import get_wsgi_application
from django.db import connections
from gunicorn.app.base import BaseApplication

from dnsrules.core import jobs
from dnsrules.queries import services

WORKERS = 1
THREADS = 8


def _background(_worker) -> None:
    """Start the jobs and the ingest, once, inside the forked worker."""
    stop = threading.Event()
    threading.Thread(target=jobs.worker, args=(stop,), daemon=True).start()
    threading.Thread(
        target=services.listen,
        args=(settings.DNSTAP_HOST, settings.DNSTAP_PORT),
        daemon=True,
    ).start()


class Application(BaseApplication):
    def __init__(self, options: dict):
        self.options = options
        super().__init__()

    def load_config(self) -> None:
        # gunicorn types cfg as optional, and it builds one before it calls
        # this. Bind it once, so the type checker can follow.
        config = self.cfg
        assert config is not None
        for key, value in self.options.items():
            config.set(key, value)

    def load(self):
        return get_wsgi_application()


class Command(BaseCommand):
    help = "Serve the website, the query log ingest, and the jobs."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--bind", default=settings.BIND)
        parser.add_argument("--threads", type=int, default=THREADS)

    def handle(self, *args, **options) -> None:
        call_command("migrate", no_input=True)
        # The migration opened a connection. gunicorn forks after this, and two
        # processes sharing one connection corrupt the protocol, so close it
        # here and let each thread open its own.
        connections.close_all()
        Application(
            {
                "bind": options["bind"],
                "control_socket_disable": True,
                "workers": WORKERS,
                "threads": options["threads"],
                "post_worker_init": _background,
            }
        ).run()
