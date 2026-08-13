"""Listen for the dnstap stream.

unbound is the client here. It connects out to `dnstap-ip`, and it reconnects
about once a second while nothing listens. So this side listens, takes one
connection at a time, and goes back to waiting when that connection ends.

One connection is one frame stream, with its own START control frame. That is
why `connections` yields a reader for each, rather than one endless byte
stream: a restart of unbound must not look like a corrupt frame.
"""

import logging
import socket
from collections.abc import Callable, Iterator

logger = logging.getLogger(__name__)

CHUNK = 65536
# unbound writes to one connection at a time. A second one means a second
# sender, which is a configuration fault worth seeing rather than serving.
BACKLOG = 1


def _chunks(connection: socket.socket) -> Iterator[bytes]:
    with connection:
        while chunk := connection.recv(CHUNK):
            yield chunk


def connections(
    host: str, port: int, *, ready: Callable[[tuple], None] | None = None
) -> Iterator[Iterator[bytes]]:
    """Yield a byte reader for each connection, forever.

    `ready` is called once the socket is listening, which lets a test learn the
    port before anything connects.
    """
    with socket.create_server(
        (host, port), backlog=BACKLOG, reuse_port=False
    ) as server:
        if ready is not None:
            ready(server.getsockname())
        logger.info("Listening for dnstap on %s.", server.getsockname())
        while True:
            connection, peer = server.accept()
            logger.info("dnstap sender connected from %s.", peer)
            yield _chunks(connection)
            logger.info("dnstap sender at %s went away.", peer)
