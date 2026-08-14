"""Serve the rules to unbound.

dnsrules renders each group's active rules as RPZ zone text and serves it over
HTTP. unbound fetches that URL. A rule change raises the serial, then tells
unbound to fetch the zone again.

Nothing here holds a lock. There is no file to interleave, and a serial rises
by one statement, so two workers that save at once both converge.
"""

import logging

from django.conf import settings
from django.db.models import F

from dnsrules.rules.models import Group, Rule
from dnsrules.unbound import control, zone

logger = logging.getLogger(__name__)


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

    Returns the zone names it asked for.

    Call this after the transaction that changed the rules has committed. A
    failed transfer then reports an error without losing the change, and
    unbound refetches on its own within the SOA refresh interval.
    """
    Group.objects.update(serial=F("serial") + 1)
    asked = []
    for group in Group.objects.all():
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
