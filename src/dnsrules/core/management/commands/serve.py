"""Run the website under gunicorn.

gunicorn goes through its Python API, not its console script, so the install
carries one entry point and the unit file names the same binary as every other
command.

Errors go to stderr, which the unit sends to the journal. There is no access
log: the journal already has one line for each restart, and a busy access log
buries it.
"""

import os
from argparse import ArgumentParser

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.wsgi import get_wsgi_application
from gunicorn.app.base import BaseApplication


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
    help = "Serve the website with gunicorn."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--bind", default=settings.BIND)
        parser.add_argument("--workers", type=int, default=settings.WORKERS)

    def handle(self, *args, **options) -> None:
        # settings.py generates a key per process when the environment has
        # none. Two workers then hold two keys, and each rejects the other's
        # session cookie, so a login lasts until the next request.
        if options["workers"] > 1 and not os.environ.get("DNSRULES_SECRET_KEY"):
            raise CommandError(
                "More than one worker needs DNSRULES_SECRET_KEY. Add a line "
                "from `dnsrules secret` to the environment file, or pass "
                "--workers 1."
            )
        Application({"bind": options["bind"], "workers": options["workers"]}).run()
