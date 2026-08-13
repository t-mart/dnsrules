"""Roll the query log into a small archive, and keep the archive for 13 months.

The raw rows live 30 days and answer anything about last week, down to the
client and the second. This archive answers what outlives them: how much each
client asked, how much was blocked, and which names led.

Two shapes, because two questions have different costs:

- `Hour` drops the name. One row for each client, each hour, blocked or not.
- `Top` keeps the leading names of a day and drops the tail.

Every statement is an upsert over whole hours or whole days, so a second run
writes the same numbers. Nothing here takes a name from outside.
"""

import logging
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Max
from django.utils import timezone

from dnsrules.queries.models import Hour, Query, Top

logger = logging.getLogger(__name__)

# Django builds a table name from the app label and the model, and these three
# are written out for the same reason partitions.py writes one out: Postgres
# cannot parameterize an identifier. A wrong name here fails every test that
# rolls anything.
QUERIES = "queries_query"
HOURS = "queries_hour"
TOPS = "queries_top"

# Names to keep for each day, for blocked and allowed apart.
TOP = 100

MONTHS = 13

_ROLL_HOURS = f"""
INSERT INTO {HOURS} (at, client, blocked, count)
SELECT date_trunc('hour', at), client, blocked, count(*)
FROM {QUERIES}
WHERE at >= %s AND at < %s
GROUP BY 1, 2, 3
ON CONFLICT (at, client, blocked) DO UPDATE SET count = EXCLUDED.count
"""

# The rank runs inside the group by, so the count it orders on is the count
# this rolls up. Blocked and allowed rank apart: a blocked name is rare and it
# would never reach a shared list.
_ROLL_DAYS = f"""
INSERT INTO {TOPS} (at, qname, blocked, count)
SELECT day, qname, blocked, tally
FROM (
    SELECT
        (at AT TIME ZONE %s)::date AS day,
        qname,
        blocked,
        count(*) AS tally,
        row_number() OVER (
            PARTITION BY (at AT TIME ZONE %s)::date, blocked
            ORDER BY count(*) DESC, qname
        ) AS place
    FROM {QUERIES}
    WHERE at >= %s AND at < %s
    GROUP BY 1, 2, 3
) ranked
WHERE place <= %s
ON CONFLICT (at, qname, blocked) DO UPDATE SET count = EXCLUDED.count
"""


def _floor_hour(moment: datetime) -> datetime:
    return moment.replace(minute=0, second=0, microsecond=0)


def _start_of_day(day: date) -> datetime:
    """The moment a local day starts, as an absolute time."""
    return timezone.make_aware(datetime.combine(day, time.min))


def _months_ago(today: date, months: int) -> date:
    """The first of the month, `months` back. It never overflows a short month."""
    index = today.year * 12 + today.month - 1 - months
    year, month = divmod(index, 12)
    return date(year, month + 1, 1)


def roll_hours(now: datetime) -> int:
    """Roll every finished hour that is not in the archive. Returns rows written.

    The current hour is left alone. It is still filling, and a rolled count
    that changes later is worse than one that arrives late.
    """
    end = _floor_hour(now)
    last = Hour.objects.aggregate(newest=Max("at"))["newest"]
    start = _floor_hour(last + timedelta(hours=1)) if last else _oldest_hour()
    if start is None or start >= end:
        return 0
    with connection.cursor() as cursor:
        cursor.execute(_ROLL_HOURS, [start, end])
        return cursor.rowcount


def roll_days(now: datetime, *, top: int = TOP) -> int:
    """Roll every finished day that is not in the archive. Returns rows written."""
    end = _start_of_day(timezone.localdate(now))
    last = Top.objects.aggregate(newest=Max("at"))["newest"]
    start = _start_of_day(last + timedelta(days=1)) if last else _oldest_hour()
    if start is None or start >= end:
        return 0
    zone = settings.TIME_ZONE
    with connection.cursor() as cursor:
        cursor.execute(_ROLL_DAYS, [zone, zone, start, end, top])
        return cursor.rowcount


def _oldest_hour() -> datetime | None:
    """Where to start when the archive is empty. None when the log is."""
    oldest = Query.objects.order_by("at").values_list("at", flat=True).first()
    return _floor_hour(oldest) if oldest else None


def prune(today: date, *, months: int = MONTHS) -> int:
    """Delete archive rows past retention. Returns the rows deleted.

    A DELETE is right here, where a DROP is right for the raw table. One day
    of the archive is near 600 rows, so this never has enough to move.
    """
    cutoff = _months_ago(today, months)
    hours, _ = Hour.objects.filter(at__lt=_start_of_day(cutoff)).delete()
    tops, _ = Top.objects.filter(at__lt=cutoff).delete()
    return hours + tops


def reconcile(
    now: datetime | None = None, *, top: int = TOP, months: int = MONTHS
) -> tuple[int, int, int]:
    """Roll what is finished, then drop what is old. Returns the three counts."""
    now = now or timezone.now()
    hours = roll_hours(now)
    days = roll_days(now, top=top)
    dropped = prune(timezone.localdate(now), months=months)
    logger.info(
        "Rolled %d hourly rows and %d daily rows. Dropped %d past %d months.",
        hours,
        days,
        dropped,
        months,
    )
    return hours, days, dropped
