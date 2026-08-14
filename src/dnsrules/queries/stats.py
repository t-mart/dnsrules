"""Counts for the dashboard.

Each function is one aggregate over one window, against the table the ingest
writes. A dashboard is read rarely next to that, so the cost belongs here.

A bar carries its share of the largest bar in its set, because a bar is drawn
as a percentage and CSS cannot divide.
"""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from django.db.models import Count, Q
from django.db.models.functions import Trunc
from django.utils import timezone

from dnsrules.queries.models import Client, Query

TOP = 10
STEPS = {"minute": timedelta(minutes=1), "hour": timedelta(hours=1)}
# A tick has room for a time. A tooltip has room for the day it fell on.
TICK = "%H:%M"
STAMPS = {"minute": "%a %H:%M", "hour": "%a %d %b %H:%M"}
BLOCKED = Q(blocked=True)


@dataclass(frozen=True)
class Bar:
    """One row of a chart: what it is, how many, and how many were stopped."""

    label: str
    count: int
    blocked: int = 0
    # What a click filters the log by. Empty where a bar links nowhere.
    key: str = ""
    share: float = 0.0

    @property
    def blocked_share(self) -> float:
        """The stopped part, against this bar rather than against the set."""
        return 100 * self.blocked / self.count if self.count else 0.0


def _scaled(bars: list[Bar]) -> list[Bar]:
    """Set each share against the largest bar, so a chart fills its width."""
    largest = max((bar.count for bar in bars), default=0)
    if not largest:
        return bars
    return [replace(bar, share=100 * bar.count / largest) for bar in bars]


def _rows(since: datetime):
    """The rows in the window, with the model ordering dropped.

    A `values().annotate()` groups by every ordering field, so the `-at` on the
    model would put each row in a group of its own.
    """
    return Query.objects.filter(at__gte=since).order_by()


def top(since: datetime, *, blocked: bool, limit: int = TOP) -> list[Bar]:
    """The names asked for most, either the stopped ones or the rest."""
    rows = _rows(since).filter(blocked=blocked)
    counted = (
        rows.values("qname").annotate(count=Count("pk")).order_by("-count")[:limit]
    )
    return _scaled(
        [
            Bar(
                label=row["qname"],
                count=row["count"],
                blocked=row["count"] if blocked else 0,
                key=row["qname"],
            )
            for row in counted
        ]
    )


def clients(since: datetime, *, limit: int = TOP) -> list[Bar]:
    """The busiest clients, each with the part of its traffic that was stopped."""
    counted = (
        _rows(since)
        .values("client")
        .annotate(count=Count("pk"), blocked=Count("pk", filter=BLOCKED))
        .order_by("-count")[:limit]
    )
    known = dict(Client.objects.values_list("address", "name"))
    return _scaled(
        [
            Bar(
                label=known.get(row["client"]) or row["client"],
                count=row["count"],
                blocked=row["blocked"],
                key=row["client"],
            )
            for row in counted
        ]
    )


def _floor(moment: datetime, kind: str) -> datetime:
    """The start of the bucket that holds `moment`, as Trunc computes it.

    Trunc works in the current time zone, so this does too.
    """
    local = timezone.localtime(moment)
    if kind == "hour":
        return local.replace(minute=0, second=0, microsecond=0)
    return local.replace(second=0, microsecond=0)


def timeline(since: datetime, kind: str, *, now: datetime | None = None) -> dict:
    """Every bucket in the window, oldest first, in the shape the chart reads.

    The two series stack, so `allowed` is what was not stopped rather than the
    whole bucket. Adding the parts is the chart's job.

    The database returns no row for a quiet bucket. A chart that skipped those
    would draw a silent hour as if it never happened, so they are made here.
    """
    counted = {
        row["bucket"]: row
        for row in _rows(since)
        .annotate(bucket=Trunc("at", kind))
        .values("bucket")
        .annotate(count=Count("pk"), blocked=Count("pk", filter=BLOCKED))
        .order_by("bucket")
    }
    data = {"labels": [], "stamps": [], "allowed": [], "blocked": []}
    moment = _floor(since, kind)
    end = timezone.localtime(now or timezone.now())
    while moment <= end:
        row = counted.get(moment)
        stopped = row["blocked"] if row else 0
        data["labels"].append(moment.strftime(TICK))
        data["stamps"].append(moment.strftime(STAMPS[kind]))
        data["blocked"].append(stopped)
        data["allowed"].append((row["count"] if row else 0) - stopped)
        moment += STEPS[kind]
    return data
