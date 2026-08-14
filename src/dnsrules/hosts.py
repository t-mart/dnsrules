"""Read `hosts.yml`, the file that Ansible renders.

Ansible owns host names, addresses, group names, and membership. It writes
`/etc/dnsrules/hosts.yml` at deploy time. dnsrules reads that file and
never writes it.

The file supplies four things: each group's unbound zone name, a name for each
address, which group applies to which host, and which networks carry managed
hosts. Subnets belong there, not in this code: `mace` serves the DHCP pool and
knows its range.

YAML, because the source is `vars/hosts.yml` and the Ansible repository is YAML
throughout. One format, and the rendered file stays readable by hand.
"""

import ipaddress
from dataclasses import dataclass
from pathlib import Path

import yaml

NAME_MAX_LENGTH = 64


class InvalidHosts(ValueError):
    """The file is absent, or it does not match the format."""


@dataclass(frozen=True, slots=True)
class Group:
    name: str
    zone: str  # the unbound RPZ zone name, for auth_zone_transfer


@dataclass(frozen=True, slots=True)
class Host:
    name: str
    addresses: tuple[str, ...]
    groups: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Network:
    """A range of addresses, and whether any policy reaches it.

    The DHCP pool is unmanaged: those hosts are absent from `vars/hosts.yml`,
    so they carry no tag and no RPZ zone applies. Saying so in the UI explains
    why a device gets no blocking.
    """

    name: str
    cidr: ipaddress.IPv4Network | ipaddress.IPv6Network
    managed: bool


@dataclass(frozen=True, slots=True)
class Hosts:
    groups: dict[str, Group]  # keyed by group name
    hosts: tuple[Host, ...]
    names: dict[str, str]  # address to host name
    networks: tuple[Network, ...]


def _object(entry: object, path: Path) -> dict:
    if not isinstance(entry, dict):
        raise InvalidHosts(f"{path} holds an entry that is not an object.")
    return entry


def _field(entry: dict, key: str, path: Path) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise InvalidHosts(f"{path} holds an entry with no {key}.")
    return value


def _strings(entry: dict, key: str, path: Path) -> tuple[str, ...]:
    values = entry.get(key, [])
    if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
        raise InvalidHosts(f"{path}: {key} must be a list of strings.")
    return tuple(values)


def _group(raw: object, path: Path) -> Group:
    entry = _object(raw, path)
    zone = _field(entry, "zone", path)
    # The zone name becomes an argument to auth_zone_transfer. A space would
    # split it into two arguments.
    if zone.split() != [zone]:
        raise InvalidHosts(f"{path}: the zone name {zone!r} holds whitespace.")
    return Group(name=_field(entry, "name", path), zone=zone)


def _network(raw: object, path: Path) -> Network:
    entry = _object(raw, path)
    text = _field(entry, "cidr", path)
    try:
        cidr = ipaddress.ip_network(text)
    except ValueError as error:
        raise InvalidHosts(f"{path}: {text!r} is not a network.") from error
    managed = entry.get("managed", True)
    if not isinstance(managed, bool):
        raise InvalidHosts(f"{path}: managed must be true or false.")
    return Network(name=_field(entry, "name", path), cidr=cidr, managed=managed)


def _host(raw: object, path: Path) -> Host:
    entry = _object(raw, path)
    return Host(
        name=_field(entry, "name", path),
        addresses=_strings(entry, "addresses", path),
        groups=_strings(entry, "groups", path),
    )


def load(path: Path) -> Hosts:
    """Read `hosts.yml`. Raises InvalidHosts for anything unusable.

    An absent file is an error, not an empty result. Empty would render every
    zone file with no rules in it.
    """
    try:
        raw = yaml.safe_load(path.read_text())
    except FileNotFoundError as error:
        raise InvalidHosts(
            f"{path} does not exist. Ansible renders it on the router. Set "
            f"DNSRULES_HOSTS_PATH to point elsewhere."
        ) from error
    except yaml.YAMLError as error:
        raise InvalidHosts(f"{path} is not valid YAML: {error}") from error
    if not isinstance(raw, dict):
        raise InvalidHosts(f"{path} does not hold an object.")

    groups: dict[str, Group] = {}
    for entry in raw.get("groups", []):
        group = _group(entry, path)
        if group.name in groups:
            raise InvalidHosts(f"{path} names the group {group.name} twice.")
        groups[group.name] = group

    hosts = tuple(_host(entry, path) for entry in raw.get("hosts", []))
    names = {address: host.name for host in hosts for address in host.addresses}
    networks = tuple(_network(entry, path) for entry in raw.get("networks", []))
    return Hosts(groups=groups, hosts=hosts, names=names, networks=networks)
