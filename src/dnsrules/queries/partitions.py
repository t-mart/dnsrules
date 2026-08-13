"""Make and remove the daily partitions of the query log.

Nothing here takes a name from outside. Postgres cannot parameterize an
identifier, so every table name is built from a date this module formats.
"""

import logging
import re
from datetime import date, timedelta

from django.db import connection

logger = logging.getLogger(__name__)

TABLE = "queries_query"
DEFAULT_PARTITION = f"{TABLE}_default"

# The name carries the day it holds. Anything else is not ours to drop.
NAME = re.compile(rf"^{TABLE}_(?P<day>\d{{8}})$")

AHEAD = 7
KEEP = 30


def name_for(day: date) -> str:
    return f"{TABLE}_{day:%Y%m%d}"


def existing() -> dict[str, date]:
    """Every daily partition, by name. The DEFAULT partition is not one."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT child.relname
            FROM pg_inherits
            JOIN pg_class parent ON parent.oid = pg_inherits.inhparent
            JOIN pg_class child ON child.oid = pg_inherits.inhrelid
            WHERE parent.relname = %s
            """,
            [TABLE],
        )
        rows = [row[0] for row in cursor.fetchall()]
    found = {}
    for row in rows:
        match = NAME.match(row)
        if match:
            found[row] = date(
                int(match["day"][:4]), int(match["day"][4:6]), int(match["day"][6:])
            )
    return found


def create(day: date) -> bool:
    """Add the partition for one day. Returns False when it was already there."""
    name = name_for(day)
    if name in existing():
        return False
    with connection.cursor() as cursor:
        cursor.execute(
            f"CREATE TABLE {name} PARTITION OF {TABLE} FOR VALUES FROM (%s) TO (%s)",
            [day, day + timedelta(days=1)],
        )
    logger.info("Created the query log partition for %s.", day)
    return True


def drop(day: date) -> bool:
    """Remove one day. Instant, and it leaves nothing to vacuum."""
    name = name_for(day)
    if name not in existing():
        return False
    with connection.cursor() as cursor:
        cursor.execute(f"DROP TABLE {name}")
    logger.info("Dropped the query log partition for %s.", day)
    return True


def reconcile(today: date | None = None, *, ahead: int = AHEAD, keep: int = KEEP):
    """Add the days that are coming, and remove the days past retention.

    Returns the days added and the days dropped.

    Run it well before the rows arrive. A day with no partition still accepts
    rows, into the DEFAULT partition, and a partition for that day can then no
    longer be created.
    """
    today = today or date.today()
    added = [day for day in _days(today, ahead) if create(day)]
    oldest = today - timedelta(days=keep)
    dropped = [day for name, day in sorted(existing().items()) if day < oldest]
    for day in dropped:
        drop(day)
    return added, dropped


def _days(today: date, ahead: int) -> list[date]:
    return [today + timedelta(days=offset) for offset in range(ahead + 1)]


def default_rows() -> int:
    """Rows that fell into the DEFAULT partition. Any is a fault to look at."""
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT count(*) FROM ONLY {DEFAULT_PARTITION}")
        return cursor.fetchone()[0]
