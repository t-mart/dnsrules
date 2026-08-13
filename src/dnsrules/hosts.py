"""Read `hosts.yml`, the file that Ansible renders.

Ansible owns host names, addresses, group names, and membership. It writes
`/etc/dnsrules/hosts.yml` at deploy time. dnsrules reads that file and
never writes it.

The file supplies three things: where to write each group's zone file, a name
for each address, and which group applies to which host.

YAML, because the source is `vars/hosts.yml` and the Ansible repository is YAML
throughout. One format, and the rendered file stays readable by hand.
"""

from dataclasses import dataclass
from pathlib import Path

import yaml

NAME_MAX_LENGTH = 64


class InvalidHosts(ValueError):
    """The file is absent, or it does not match the format."""


@dataclass(frozen=True, slots=True)
class Group:
    name: str
    zone: str  # the unbound zone name, for auth_zone_reload
    zonefile: Path  # the file dnsrules renders


@dataclass(frozen=True, slots=True)
class Host:
    name: str
    addresses: tuple[str, ...]
    groups: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Hosts:
    groups: dict[str, Group]  # keyed by group name
    hosts: tuple[Host, ...]
    names: dict[str, str]  # address to host name


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
    # The zone name becomes an argument to auth_zone_reload. A space would
    # split it into two arguments.
    if zone.split() != [zone]:
        raise InvalidHosts(f"{path}: the zone name {zone!r} holds whitespace.")
    return Group(
        name=_field(entry, "name", path),
        zone=zone,
        zonefile=Path(_field(entry, "zonefile", path)),
    )


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
    return Hosts(groups=groups, hosts=hosts, names=names)
