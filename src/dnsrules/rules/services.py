"""Serve the rules to unbound.

dnsrules renders each group's active rules as RPZ zone text and serves it over
HTTP. unbound fetches that URL. A rule change raises the serial, then tells
unbound to fetch the zone again.

Nothing here holds a lock. There is no file to interleave, and a serial rises
by one statement, so two workers that save at once both converge.
"""

import logging
import time

from django.conf import settings
from django.db.models import F

from dnsrules.rules.models import Group, Rule
from dnsrules.unbound import control, zone

logger = logging.getLogger(__name__)

# How long to wait for unbound to hold the serial it was just told about, and
# how often to ask. The job runs in a worker, so the page never waits on this.
CONFIRM_FOR = 2.0
CONFIRM_EVERY = 0.05


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


def _behind(expected: dict[str, int]) -> list[str]:
    """Name each zone unbound does not hold at the serial it should.

    A zone ahead of the expected serial is not behind. Two changes in a row
    can leave unbound holding the later one, and that one carries this change.
    """
    held = control.auth_zones(
        settings.UNBOUND_CONTROL_HOST, settings.UNBOUND_CONTROL_PORT
    )
    problems = []
    for name, serial in expected.items():
        if name not in held:
            problems.append(f"unbound has no zone {name}")
            continue
        got = held[name]
        if got is None:
            problems.append(f"unbound has never fetched {name}")
        elif got < serial:
            problems.append(f"unbound holds {name} at serial {got}, not {serial}")
    return problems


def confirm(
    expected: dict[str, int],
    *,
    timeout: float = CONFIRM_FOR,
    interval: float = CONFIRM_EVERY,
    clock=time.monotonic,
    sleep=time.sleep,
) -> list[str]:
    """Wait for unbound to hold each serial. Returns what it never took.

    The transfer command answers before it fetches, so the first read can be
    honestly early. Measured against 1.26.0 the serial arrives in about 30 ms,
    and the timeout is far longer because a false alarm is worse than a wait.
    """
    deadline = clock() + timeout
    while True:
        problems = _behind(expected)
        if not problems or clock() >= deadline:
            return problems
        sleep(interval)


def reconcile() -> list[str]:
    """Raise every serial, tell unbound to fetch, then check that it did.

    Returns the zone names it asked for, and raises when unbound does not
    hold them.

    Call this after the transaction that changed the rules has committed. A
    failed transfer then reports an error without losing the change, and
    unbound refetches on its own within the SOA refresh interval.
    """
    Group.objects.update(serial=F("serial") + 1)
    groups = list(Group.objects.all())
    for group in groups:
        control.auth_zone_transfer(
            settings.UNBOUND_CONTROL_HOST, settings.UNBOUND_CONTROL_PORT, group.zone
        )
    # The transfer reply means nothing, so ask unbound what it holds. This is
    # the only thing that tells a rule that landed from one that did not.
    problems = confirm({group.zone: group.serial for group in groups})
    if problems:
        raise control.ControlError("; ".join(problems))
    return [group.zone for group in groups]


def prune() -> int:
    """Delete expired rules and tell unbound. Returns the count."""
    count, _ = Rule.objects.expired().delete()
    if count:
        reconcile()
    return count
