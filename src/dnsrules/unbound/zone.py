"""Render the rules as RPZ zone text.

dnsrules serves this text over HTTP and unbound fetches it. Nothing here
touches a file.

Nothing here builds a right hand side from user input. `RIGHT_HAND_SIDE` holds
every legal one, and a rule selects from it. Two rules once fused into one
line:

    google-analytics.com CNAME rpz-passthru.example.com CNAME .

`rpz-passthru.example.com` is a legal CNAME target, so unbound loaded the line
without complaint and an unblock became a block of another kind. Validating the
left hand side and fixing the right hand side removes that class of fault.
"""

import enum
from collections.abc import Iterable
from dataclasses import dataclass

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

TTL = 60
# unbound refetches on this interval when a transfer trigger is lost, so it is
# the worst case for a saved rule to reach the resolver.
REFRESH = 3600
RETRY = 600
EXPIRE = 86400
NEGATIVE_TTL = 60


@dataclass(frozen=True, slots=True)
class Record:
    domain: str
    action: Action


def header(serial: int) -> str:
    """The SOA and NS that every RPZ zone needs.

    unbound accepts a transfer only when the serial rises, so the caller owns
    the serial and it has to outlive a restart of either side.
    """
    return (
        f"$TTL {TTL}\n"
        f"@ SOA localhost. root.localhost. "
        f"{serial} {REFRESH} {RETRY} {EXPIRE} {NEGATIVE_TTL}\n"
        f"@ NS localhost.\n"
    )


def render(records: Iterable[Record], serial: int) -> str:
    """Return the whole zone text: the header, then one line per rule.

    Sorted by domain, so the text only changes when the rules change. Raises
    InvalidDomain for a bad name, ValueError for a repeated one.
    """
    lines: dict[str, str] = {}
    for record in records:
        domain = normalize(record.domain)
        if domain in lines:
            raise ValueError(f"{domain} has more than one rule.")
        lines[domain] = f"{domain} {RIGHT_HAND_SIDE[Action(record.action)]}"
    if not lines:
        return header(serial)
    body = "".join(f"{lines[domain]}\n" for domain in sorted(lines))
    return f"{header(serial)}\n{body}"
