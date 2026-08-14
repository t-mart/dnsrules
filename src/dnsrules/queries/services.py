"""Read a dnstap stream and write the query log.

The pipeline: bytes, frames, records, exchanges, rows. Each stage is a
generator, so memory holds one batch and the queries still waiting for an
answer, never the whole stream.
"""

import logging
import time
from collections.abc import Iterable, Iterator

from django.conf import settings
from django.db import OperationalError, connection

from dnsrules.queries import partitions, rollups
from dnsrules.queries.models import Query
from dnsrules.unbound import framestream, receiver
from dnsrules.unbound.dnstap import Exchange, InvalidMessage, Record, decode, pair
from dnsrules.unbound.framestream import InvalidStream

logger = logging.getLogger(__name__)

BATCH = 500
INTERVAL = 1.0


def retention() -> None:
    """Archive the finished hours and days, then move the partitions on.

    Order matters. A rollup that fails must leave the day it had not read yet,
    so nothing here drops a partition before the archive holds it.
    """
    hours, days, dropped = rollups.reconcile()
    logger.info(
        "Rolled %d hourly and %d daily rows, and dropped %d past their months.",
        hours,
        days,
        dropped,
    )
    added, gone = partitions.reconcile()
    logger.info("Added %d partitions and dropped %d.", len(added), len(gone))
    over = partitions.enforce_cap(settings.LOG_MAX_BYTES)
    if over:
        logger.warning(
            "%d days went early, from %s to %s, because the log passed its cap.",
            len(over),
            over[0],
            over[-1],
        )
    stray = partitions.default_rows()
    if stray:
        logger.warning(
            "%d rows sit in the DEFAULT partition. Their day had no partition "
            "when they arrived, and it can no longer take one.",
            stray,
        )


def _records(frames: Iterable[bytes]) -> Iterator[Record]:
    """Decode each frame. One bad frame must not end the stream."""
    for frame in frames:
        try:
            yield decode(frame)
        except InvalidMessage as problem:
            logger.warning("Skipped a dnstap frame: %s", problem)


def store(exchanges: Iterable[Exchange]) -> int:
    """Write one batch. Returns the row count.

    Retries once on a broken connection, because the database is on another
    host and a restart there must not end the ingest.
    """
    rows = [
        Query(
            at=exchange.at,
            client=str(exchange.client),
            qname=exchange.qname,
            qtype=exchange.qtype,
            rcode=exchange.rcode or "",
            reply_ms=exchange.reply_ms,
            blocked=exchange.blocked,
        )
        for exchange in exchanges
    ]
    if not rows:
        return 0
    try:
        Query.objects.bulk_create(rows)
    except OperationalError:
        logger.warning("The database connection failed. Reconnecting once.")
        connection.close()
        Query.objects.bulk_create(rows)
    return len(rows)


def ingest(
    chunks: Iterable[bytes],
    *,
    batch: int = BATCH,
    interval: float = INTERVAL,
    clock=time.monotonic,
) -> int:
    """Read one connection to its end, and write what it carried.

    A batch goes out on `batch` rows or on `interval` seconds, whichever comes
    first. The tick matters at this rate: a house makes about three queries a
    second, so a size-only rule would hold rows for minutes.
    """
    written = 0
    waiting: list[Exchange] = []
    last = clock()
    for exchange in pair(_records(framestream.read(chunks))):
        waiting.append(exchange)
        if len(waiting) >= batch or clock() - last >= interval:
            written += store(waiting)
            waiting.clear()
            last = clock()
    return written + store(waiting)


def listen(host: str, port: int) -> None:
    """Take one dnstap connection after another, and write what each carries.

    unbound connects out and reconnects on its own, so this never gives up on
    a stream that ended badly.
    """
    # Insurance. The retention job makes the partitions, and a missed run would
    # send every row to the DEFAULT partition.
    partitions.reconcile()
    for chunks in receiver.connections(host, port):
        try:
            written = ingest(chunks)
        except InvalidStream as problem:
            logger.warning("The dnstap stream ended badly: %s", problem)
            continue
        logger.info("Wrote %d rows from one dnstap connection.", written)
