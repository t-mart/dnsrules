"""Reconcile the rules table into the zone files, one file for each group.

The order is fixed: read the inventory, take the lock, read the rules, render,
write, reload. Every step after a read depends on that read having worked.
"""

import logging
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.db import connection, models, transaction

from dnsrules import inventory
from dnsrules.rules.models import Group, Rule
from dnsrules.unbound import control, zone

logger = logging.getLogger(__name__)

# One lock guards render, write, and reload. Two workers rendering at once
# interleave their writes. A transaction advisory lock releases on commit or
# rollback, so it cannot leak the way pg_advisory_lock can.
LOCK_KEY = 0x646E7372  # "dnsr"


def read_inventory() -> inventory.Inventory:
    return inventory.load(settings.INVENTORY_PATH)


def sync_groups(entries: inventory.Inventory) -> None:
    """Give every inventory group a row, so a rule can point at it.

    Nothing is deleted here. A group that leaves the inventory keeps its rules.
    """
    Group.objects.bulk_create(
        [Group(name=name) for name in entries.groups], ignore_conflicts=True
    )


def stale_groups(entries: inventory.Inventory) -> models.QuerySet:
    """Groups that hold rules but no longer appear in the inventory.

    Staleness is read from the inventory on each call rather than stored. A
    stored flag drifts as soon as a deploy changes the file.
    """
    return Group.objects.exclude(name__in=list(entries.groups))


def reconcile() -> dict[str, str]:
    """Render each group's active rules to its zone file, then reload unbound.

    Returns the zone text for each group that was written.

    Raises rather than writing when a read fails. A render from an unreachable
    database writes a zone with no rules in it and silently drops every block.
    Nothing here catches that: the reads come first, and an exception leaves
    every file untouched.

    Call this after the transaction that changed the rules has committed. A
    failed reload then reports an error without losing the change, and the next
    reconcile converges the files on the table.
    """
    entries = read_inventory()
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK_KEY])
        sync_groups(entries)
        records = defaultdict(list)
        for rule in Rule.objects.active().select_related("group"):
            records[rule.group.name].append(
                zone.Record(rule.domain, zone.Action(rule.action))
            )
        for name in set(records) - set(entries.groups):
            logger.warning(
                "The group %s is not in the inventory. Its %d rules are stale "
                "and reach no zone file.",
                name,
                len(records[name]),
            )
        written = {}
        for name, group in entries.groups.items():
            text = zone.render(records[name], zone.read_header(group.zonefile))
            zone.write(group.zonefile, text, mode=settings.UNBOUND_ZONE_MODE)
            reload_zone(group.zone)
            written[name] = text
    return written


def reload_zone(name: str) -> None:
    """Make unbound reread one zone file.

    An empty control socket setting means no unbound runs here, which is the
    development case. Every other fault stays an error, because a reload that
    fails quietly leaves unbound serving the previous rules while the website
    reports success.
    """
    socket_path = settings.UNBOUND_CONTROL_SOCKET
    if not socket_path:
        logger.warning(
            "DNSRULES_CONTROL_SOCKET is empty. Wrote the zone file for %s and "
            "skipped the reload.",
            name,
        )
        return
    control.auth_zone_reload(Path(socket_path), name)


def prune() -> int:
    """Delete expired rules and rewrite the zone files. Returns the count."""
    count, _ = Rule.objects.expired().delete()
    if count:
        reconcile()
    return count
