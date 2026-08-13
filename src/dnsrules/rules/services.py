"""Reconcile the rules table into the zone file.

The order is fixed: take the lock, read, render, write, reload. Every step
after the read depends on the read having worked.
"""

import logging
from pathlib import Path

from django.conf import settings
from django.db import connection, transaction

from dnsrules.rules.models import Rule
from dnsrules.unbound import control, zone

logger = logging.getLogger(__name__)

# One lock guards render, write, and reload. Two workers rendering at once
# interleave their writes. A transaction advisory lock releases on commit or
# rollback, so it cannot leak the way pg_advisory_lock can.
LOCK_KEY = 0x646E7372  # "dnsr"


def reconcile() -> str:
    """Render every active rule to the zone file, then reload unbound.

    Returns the zone text.

    Raises rather than writing when the database read fails. A render from an
    unreachable database writes a zone with no rules in it and silently drops
    every block. Nothing here catches that: the read comes first, and an
    exception leaves the file untouched.

    Call this after the transaction that changed the rules has committed. A
    failed reload then reports an error without losing the change, and the next
    reconcile converges the file on the table.
    """
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", [LOCK_KEY])
        records = [
            zone.Record(rule.domain, zone.Action(rule.action))
            for rule in Rule.objects.active()
        ]
        path = settings.UNBOUND_ZONE_PATH
        text = zone.render(records, zone.read_header(path))
        zone.write(path, text, mode=settings.UNBOUND_ZONE_MODE)
        reload_zone()
    return text


def reload_zone() -> None:
    """Make unbound reread the zone file.

    An empty control socket setting means no unbound runs here, which is the
    development case. Every other fault stays an error, because a reload that
    fails quietly leaves unbound serving the previous rules while the website
    reports success.
    """
    socket_path = settings.UNBOUND_CONTROL_SOCKET
    if not socket_path:
        logger.warning(
            "DNSRULES_CONTROL_SOCKET is empty. Wrote the zone file and skipped "
            "the reload."
        )
        return
    control.auth_zone_reload(Path(socket_path), settings.UNBOUND_ZONE_NAME)


def prune() -> int:
    """Delete expired rules and rewrite the zone file. Returns the count."""
    count, _ = Rule.objects.expired().delete()
    if count:
        reconcile()
    return count
