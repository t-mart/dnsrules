"""Read a dnstap stream and write the query log.

The pipeline: bytes, frames, records, exchanges, rows. Each stage is a
generator, so memory holds one batch and the queries still waiting for an
answer, never the whole stream.
"""

import logging
import time
from collections.abc import Iterable, Iterator
from datetime import timedelta
from functools import lru_cache

from django.db import OperationalError, connection
from django.utils import timezone

from dnsrules.queries.models import BlockedBy, Query
from dnsrules.rules.models import Rule
from dnsrules.unbound import framestream, receiver
from dnsrules.unbound.dnstap import Exchange, InvalidMessage, Record, decode, pair
from dnsrules.unbound.framestream import InvalidStream
from dnsrules.unbound.zone import Action

logger = logging.getLogger(__name__)

BATCH = 500
INTERVAL = 1.0
KEEP = timedelta(days=30)
# Rules change by hand, so a minute of staleness costs at most a mislabelled
# row. Reading the table for each of 250,000 rows a day would not.
RULES_TTL = 60.0


def blocking_domains() -> frozenset[str]:
    """Every name a dnsrules rule blocks right now."""
    return frozenset(
        Rule.objects.active()
        .exclude(action=Action.ALLOW)
        .values_list("domain", flat=True)
    )


@lru_cache(maxsize=1)
def _bucketed(bucket: int) -> frozenset[str]:
    return blocking_domains()


def cached_blocking_domains(ttl: float = RULES_TTL) -> frozenset[str]:
    """`blocking_domains()`, read at most once in each `ttl` seconds.

    The bucket is the cache key, so the old entry falls out on its own and
    nothing here holds a timestamp.
    """
    return _bucketed(int(time.monotonic() // ttl))


def blocked_by(exchange: Exchange, rules: frozenset[str]) -> str:
    """Name what stopped this answer, or empty when nothing did.

    A rule is checked first, and it is exact. The in-band signal covers the
    feed, and it cannot see a NODATA rule at all.
    """
    if exchange.qname in rules:
        return BlockedBy.RULE
    return BlockedBy.FEED if exchange.blocked else ""


def retention(keep: timedelta = KEEP) -> int:
    """Delete the rows past the retention window. Returns the count.

    One statement. The BRIN index on `at` finds the range, and the rows are
    contiguous on disk, so there is nothing here worth optimising.
    """
    count, _ = Query.objects.filter(at__lt=timezone.now() - keep).delete()
    logger.info("Deleted %d query rows older than %s.", count, keep)
    return count


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
    rules = cached_blocking_domains()
    rows = [
        Query(
            at=exchange.at,
            client=str(exchange.client),
            qname=exchange.qname,
            qtype=exchange.qtype,
            rcode=exchange.rcode or "",
            reply_ms=exchange.reply_ms,
            blocked_by=blocked_by(exchange, rules),
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
    for chunks in receiver.connections(host, port):
        try:
            written = ingest(chunks)
        except InvalidStream as problem:
            logger.warning("The dnstap stream ended badly: %s", problem)
            continue
        logger.info("Wrote %d rows from one dnstap connection.", written)
