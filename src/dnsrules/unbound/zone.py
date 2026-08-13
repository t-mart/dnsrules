"""Render and write the runtime rules RPZ zone.

The zone file is rendered output. The rules live in the database, and this
module turns them into the exact text unbound loads.

Nothing here builds a right hand side from user input. `RIGHT_HAND_SIDE` holds
every legal one, and a rule selects from it. On mace, two rules once fused into
one line:

    google-analytics.com CNAME rpz-passthru.example.com CNAME .

`rpz-passthru.example.com` is a legal CNAME target, so unbound loaded the line
without complaint, `auth_zone_reload` still returned ok, and an unblock became a
block of another kind. Validating the left hand side and fixing the right hand
side removes that class of fault.
"""

import enum
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from dnsrules.unbound.domain import normalize


class Action(enum.StrEnum):
    """What a rule does. The value is what the database stores."""

    BLOCK = "block"
    BLOCK_NODATA = "block_nodata"
    ALLOW = "allow"


# The complete set of right hand sides. A rule chooses one. Nothing builds one.
RIGHT_HAND_SIDE = {
    Action.BLOCK: "CNAME .",  # answer NXDOMAIN
    Action.BLOCK_NODATA: "CNAME *.",  # answer NODATA
    Action.ALLOW: "CNAME rpz-passthru.",  # skip every later zone
}

# Record types that mark the start of the rules. Everything above the first one
# is the header.
_RECORD_TYPES = frozenset({"CNAME", "A", "AAAA"})

# Used only when the zone file is absent, which on mace it never is: Ansible
# creates it once, and the real header is read back from it.
FALLBACK_HEADER = """\
$TTL 3600
@ SOA localhost. root.localhost. 1 14400 3600 86400 3600
  NS  localhost.
"""


@dataclass(frozen=True, slots=True)
class Record:
    domain: str
    action: Action


def _is_rule(line: str) -> bool:
    if line.lstrip().startswith(";"):
        return False
    parts = line.split()
    return len(parts) >= 2 and parts[1].upper() in _RECORD_TYPES


def read_header(path: Path) -> str:
    """Return the lines above the first rule, with trailing blanks removed.

    Ansible writes the SOA, the NS, and a comment about the format, then never
    touches the file again. Read that header back rather than keep a copy here,
    so the two cannot drift.
    """
    try:
        text = path.read_text()
    except FileNotFoundError:
        return FALLBACK_HEADER
    lines = []
    for line in text.splitlines():
        if _is_rule(line):
            break
        lines.append(line)
    while lines and not lines[-1].strip():
        lines.pop()
    return "".join(f"{line}\n" for line in lines)


def render(records: Iterable[Record], header: str) -> str:
    """Return the whole zone text: the header, then one line per rule.

    Sorted by domain, so the file only changes when the rules change. Raises
    InvalidDomain for a bad name, ValueError for a repeated one.
    """
    lines: dict[str, str] = {}
    for record in records:
        domain = normalize(record.domain)
        if domain in lines:
            raise ValueError(f"{domain} has more than one rule.")
        lines[domain] = f"{domain} {RIGHT_HAND_SIDE[Action(record.action)]}"
    if not lines:
        return header
    body = "".join(f"{lines[domain]}\n" for domain in sorted(lines))
    return f"{header}\n{body}"


def write(path: Path, text: str, *, mode: int = 0o644) -> None:
    """Write the zone text atomically, so unbound never reads a half file.

    The temporary file goes in the same directory, because rename is atomic
    only within one filesystem.

    The directory must exist. On the router unbound owns it, so creating it
    here would hide a wrong path behind a directory nothing reads.
    """
    if not path.parent.is_dir():
        raise FileNotFoundError(
            f"The zone directory {path.parent} does not exist. Create it, or "
            f"set DNSRULES_ZONE_PATH."
        )
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        os.unlink(temporary)
        raise
