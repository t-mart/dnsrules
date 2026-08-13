"""Validate domain names before they reach a zone file.

The pattern is a copy of the one in `vars/schemas/unbound_blocklist.schema.json`
in the mace repository. Keep the two identical. mace validates its own blocklist
with it, and both files feed the same resolver.
"""

import re

# Optional `*.` prefix, then one or more labels of 1 to 63 characters, then an
# optional trailing dot. Match with fullmatch, never with match: `$` also
# matches before a final newline, and a newline is how a rule line splits in
# two.
PATTERN = re.compile(
    r"^(\*\.)?([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.?$"
)

MAX_LENGTH = 253


class InvalidDomain(ValueError):
    """The text is not a domain name."""


def normalize(text: str) -> str:
    """Return the name as a zone file spells it, or raise InvalidDomain.

    Lower case, and no trailing dot. unbound reads the left hand side of an RPZ
    rule relative to the zone origin, and both mace and the verification recipe
    write it bare.
    """
    candidate = text.strip().lower()
    if not candidate:
        raise InvalidDomain("The domain is empty.")
    # Match before removing the trailing dot, not after. The pattern allows one
    # trailing dot, so stripping first would let `example.com..` through.
    if not PATTERN.fullmatch(candidate):
        raise InvalidDomain(f"{text!r} is not a domain name.")
    name = candidate.removesuffix(".")
    if len(name) > MAX_LENGTH:
        raise InvalidDomain(f"The domain is longer than {MAX_LENGTH} characters.")
    return name
