"""Serve the rules to unbound.

dnsrules renders each group's active rules as RPZ zone text and serves it over
HTTP. unbound fetches that URL. A rule change raises the serial, then tells
unbound to fetch the zone again.

Nothing here holds a lock. There is no file to interleave, and a serial rises
by one statement, so two workers that save at once both converge.
"""

import logging

from django.conf import settings
from django.db import models
from django.db.models import F

from dnsrules import hosts
from dnsrules.rules.models import Group, Rule
from dnsrules.unbound import control, zone

logger = logging.getLogger(__name__)


def read_hosts() -> hosts.Hosts:
    return hosts.load(settings.HOSTS_PATH)


def sync_groups(entries: hosts.Hosts) -> None:
    """Give every group in `hosts.yml` a row, so a rule can point at it.

    Nothing is deleted here. A group that leaves the file keeps its rules.
    """
    Group.objects.bulk_create(
        [Group(name=name) for name in entries.groups], ignore_conflicts=True
    )


def stale_groups(entries: hosts.Hosts) -> models.QuerySet:
    """Groups that hold rules but no longer appear in `hosts.yml`.

    Staleness is read from the file on each call rather than stored. A stored
    flag drifts as soon as a deploy changes the file.
    """
    return Group.objects.exclude(name__in=list(entries.groups))


def zone_text(group: Group) -> str:
    """One group's whole RPZ zone, exactly as unbound fetches it.

    Rendered on each request rather than stored. The rules are the record, and
    a cached copy is one more thing that drifts from them.
    """
    records = [
        zone.Record(rule.domain, zone.Action(rule.action))
        for rule in Rule.objects.active().filter(group=group)
    ]
    # ty reads a model field as its descriptor, never as the value it holds.
    return zone.render(records, group.serial)  # ty: ignore[invalid-argument-type]


def reconcile() -> list[str]:
    """Raise every serial, then tell unbound to fetch each zone again.

    Returns the zone names it asked for. A group that left `hosts.yml` is not
    among them, because no RPZ block points at it.

    Call this after the transaction that changed the rules has committed. A
    failed transfer then reports an error without losing the change, and
    unbound refetches on its own within the SOA refresh interval.
    """
    entries = read_hosts()
    sync_groups(entries)
    Group.objects.update(serial=F("serial") + 1)
    asked = []
    for group in entries.groups.values():
        control.auth_zone_transfer(
            settings.UNBOUND_CONTROL_HOST, settings.UNBOUND_CONTROL_PORT, group.zone
        )
        asked.append(group.zone)
    return asked


def prune() -> int:
    """Delete expired rules and tell unbound. Returns the count."""
    count, _ = Rule.objects.expired().delete()
    if count:
        reconcile()
    return count
