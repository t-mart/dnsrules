"""Console entry point. Every command is a Django management command."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dnsrules.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
