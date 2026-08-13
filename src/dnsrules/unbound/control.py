"""Drive unbound through its control socket.

unbound-control speaks a one line text protocol. Over a unix socket it uses no
TLS, because unbound skips certificates for local sockets, so this needs
neither a subprocess nor a certificate.
"""

import socket
from pathlib import Path

VERSION = "UBCT1"
TIMEOUT = 5.0


class ControlError(RuntimeError):
    """unbound refused the command, or the socket is out of reach."""


def command(socket_path: Path, text: str, *, timeout: float = TIMEOUT) -> str:
    """Run one control command and return unbound's reply."""
    if "\n" in text or "\r" in text:
        raise ControlError("A control command cannot contain a newline.")
    chunks = []
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        try:
            connection.connect(str(socket_path))
            connection.sendall(f"{VERSION} {text}\n".encode())
            # unbound answers one command per connection, then closes.
            while chunk := connection.recv(4096):
                chunks.append(chunk)
        except OSError as error:
            raise ControlError(f"{socket_path}: {error}") from error
    reply = b"".join(chunks).decode()
    if reply.startswith("error"):
        raise ControlError(reply.strip())
    return reply


def auth_zone_reload(socket_path: Path, zone: str, **kwargs: float) -> str:
    """Make unbound reread the zone file. No restart, and no cache flush.

    unbound applies RPZ before the cache, so a removed rule takes effect at
    once even though the old answer is still cached.
    """
    return command(socket_path, f"auth_zone_reload {zone}", **kwargs)
