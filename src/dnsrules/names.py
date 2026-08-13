"""Name each client address.

Three sources, in order:

1. `hosts.yml`, which Ansible renders from `vars/hosts.yml`. A host has several
   addresses, and every one of them names the same host.
2. `tailscale status --json`, read at runtime. The tailnet hands out addresses
   that Ansible never sees.
3. Nothing. Show the address.

A client outside every managed network gets no blocking, because it carries no
tag in `unbound.conf`. The UI says so, since that explains the absence.
"""

import ipaddress
import json
import logging
import subprocess
import time
from dataclasses import dataclass
from functools import lru_cache

from dnsrules.hosts import Hosts

logger = logging.getLogger(__name__)

TAILSCALE = ("tailscale", "status", "--json")
TIMEOUT = 2.0
# The tailnet changes when a device joins, which is rare. One minute of staleness
# costs nothing and keeps a subprocess off the request path.
TTL = 60.0

Address = ipaddress.IPv4Address | ipaddress.IPv6Address


@dataclass(frozen=True, slots=True)
class Client:
    address: str
    name: str  # the address itself when nothing names it
    network: str  # empty when no network in hosts.yml holds it
    managed: bool
    groups: tuple[str, ...]

    @property
    def known(self) -> bool:
        return self.name != self.address


def tailnet() -> dict[str, str]:
    """Tailnet addresses to names. Empty when tailscale is absent or broken."""
    try:
        done = subprocess.run(
            TAILSCALE, capture_output=True, timeout=TIMEOUT, check=True, text=True
        )
        status = json.loads(done.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as problem:
        logger.info("No tailnet names: %s", problem)
        return {}
    found = {}
    for peer in [status.get("Self") or {}, *(status.get("Peer") or {}).values()]:
        name = (peer.get("DNSName") or "").split(".")[0] or peer.get("HostName")
        for address in peer.get("TailscaleIPs") or []:
            if name:
                found[address] = name
    return found


@lru_cache(maxsize=1)
def _bucketed(bucket: int) -> dict[str, str]:
    return tailnet()


def cached_tailnet(ttl: float = TTL) -> dict[str, str]:
    """`tailnet()`, run at most once in each `ttl` seconds.

    The bucket is the cache key, so the entry falls out on its own and nothing
    here holds a timestamp.
    """
    return _bucketed(int(time.monotonic() // ttl))


def directory(hosts: Hosts, *, tailnet_names: dict[str, str] | None = None):
    """Return a function from an address to a Client.

    Built once for each page, so a table of 50 rows costs one read of each
    source rather than 50. Tailnet names are passed in, never fetched here: a
    subprocess belongs to a caller that knows it wants one.
    """
    names = dict(tailnet_names or {})
    names.update(hosts.names)  # hosts.yml wins, because Ansible is the record
    groups = {
        address: host.groups for host in hosts.hosts for address in host.addresses
    }

    def describe(address: str | Address) -> Client:
        text = str(address)
        try:
            parsed = ipaddress.ip_address(text)
        except ValueError:
            return Client(text, text, "", False, ())
        network = next(
            (entry for entry in hosts.networks if parsed in entry.cidr), None
        )
        return Client(
            address=text,
            name=names.get(text, text),
            network=network.name if network else "",
            managed=network.managed if network else False,
            groups=groups.get(text, ()),
        )

    return describe
