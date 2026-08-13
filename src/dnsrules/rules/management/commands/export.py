import json
from argparse import ArgumentParser
from typing import Any

import yaml
from django.core.management.base import BaseCommand

from dnsrules.rules.models import Rule

FORMATS = ["yaml", "json"]


def dump(rules: list[dict], style: str) -> str:
    if style == "json":
        return json.dumps(rules, indent=2)
    return yaml.safe_dump(rules, sort_keys=False, allow_unicode=True)


class Command(BaseCommand):
    help = "Print every rule. Commit the output as a backup."

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--format", choices=FORMATS, default=FORMATS[0])

    def handle(self, *args, **options) -> None:
        # The group structure and the feed URLs live in the mace repository and
        # survive a rebuild. The rules live only here, so they need a copy that
        # git holds.
        rules: list[dict[str, Any]] = [
            {
                "group": rule.group.name,
                "domain": rule.domain,
                "action": rule.action,
                "source": rule.source,
                "expires_at": rule.expires_at.isoformat() if rule.expires_at else None,
                "note": rule.note,
            }
            for rule in Rule.objects.select_related("group")
        ]
        self.stdout.write(dump(rules, options["format"]))
