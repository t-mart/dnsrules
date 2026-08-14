"""Drive unbound through its remote control interface.

unbound-control speaks a one line text protocol. `control-use-cert: no` turns
TLS off for a localhost interface, so this needs no certificate, no subprocess,
and no unix socket.
"""

import socket

VERSION = "UBCT1"
TIMEOUT = 5.0


class ControlError(RuntimeError):
    """unbound refused the command, or the port is out of reach."""


def command(host: str, port: int, text: str, *, timeout: float = TIMEOUT) -> str:
    """Run one control command and return unbound's reply."""
    if "\n" in text or "\r" in text:
        raise ControlError("A control command cannot contain a newline.")
    chunks = []
    try:
        with socket.create_connection((host, port), timeout=timeout) as connection:
            connection.sendall(f"{VERSION} {text}\n".encode())
            # unbound answers one command per connection, then closes.
            while chunk := connection.recv(4096):
                chunks.append(chunk)
    except OSError as error:
        raise ControlError(f"{host}:{port}: {error}") from error
    reply = b"".join(chunks).decode()
    if reply.startswith("error"):
        raise ControlError(reply.strip())
    return reply


def auth_zone_transfer(host: str, port: int, zone: str, **kwargs: float) -> str:
    """Make unbound fetch the zone again, now.

    unbound takes the transfer only when the serial has risen. RPZ is applied
    before the cache, so a changed rule takes effect at once, even where the
    old answer is still cached.
    """
    return command(host, port, f"auth_zone_transfer {zone}", **kwargs)
