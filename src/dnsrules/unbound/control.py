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

    The reply says nothing. Measured against 1.26.0, this answers "ok" before
    the fetch runs, and it answers "ok" when the fetch fails outright. Read the
    serial back with `auth_zones` to learn what happened.
    """
    return command(host, port, f"auth_zone_transfer {zone}", **kwargs)


def parse_auth_zones(reply: str) -> dict[str, int | None]:
    """Read a `list_auth_zones` reply as zone name and the serial it holds.

    unbound writes one zone per line, and it ends each name with a dot:

        test_feed.	serial 1	 since 1786684178 2026-08-14T05:09:38
        dnsrules.	no serial

    A zone unbound has never fetched says "no serial", which is None here.
    """
    zones: dict[str, int | None] = {}
    for line in reply.splitlines():
        words = line.split()
        if not words:
            continue
        name, rest = words[0], words[1:]
        serial = None
        if "serial" in rest:
            after = rest[rest.index("serial") + 1 :]
            if after and after[0].isdigit():
                serial = int(after[0])
        zones[name.rstrip(".")] = serial
    return zones


def auth_zones(host: str, port: int, **kwargs: float) -> dict[str, int | None]:
    """Every auth and RPZ zone unbound holds, with the serial it holds."""
    return parse_auth_zones(command(host, port, "list_auth_zones", **kwargs))
