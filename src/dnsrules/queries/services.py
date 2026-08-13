"""Read a dnstap stream and write the query log.

The pipeline: bytes, frames, records, exchanges, rows. Each stage is a
generator, so memory holds one batch and the queries still waiting for an
answer, never the whole stream.
"""

import logging
import time
from collections.abc import Iterable, Iterator

from django.db import OperationalError, connection

from dnsrules.queries.models import Query
from dnsrules.unbound import framestream
from dnsrules.unbound.dnstap import Exchange, InvalidMessage, Record, decode, pair

logger = logging.getLogger(__name__)

BATCH = 500
INTERVAL = 1.0


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
