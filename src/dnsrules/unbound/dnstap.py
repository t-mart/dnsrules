"""Turn one dnstap frame into the fields the query log needs.

Each frame payload is a protobuf `dnstap.Dnstap` message. The schema is
`assets/dnstap.proto`, copied from the dnstap project by way of the unbound
source. `dnstap_pb2.py` is generated from it and committed, so an install needs
no protoc. Run `just proto` after a schema change.

Two facts about unbound, both read from its source:

- It never fills the `policy` field, so a dnstap message never says which RPZ
  zone acted. The journal says that.
- A client response carries `response_time` only, never `query_time`. Reply
  time is the gap between the two messages, so the ingest must pair them.
"""

import ipaddress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import dns.exception
import dns.flags
import dns.message
import dns.rcode
import dns.rdatatype
from google.protobuf.message import DecodeError

from dnsrules.unbound import dnstap_pb2

Message = dnstap_pb2.Message
CLIENT_QUERY = Message.CLIENT_QUERY
CLIENT_RESPONSE = Message.CLIENT_RESPONSE

# Only the client side. It taps the client interface, so it covers cache hits.
# The resolver and forwarder types carry no client address.
KEEP = frozenset({CLIENT_QUERY, CLIENT_RESPONSE})


class InvalidMessage(ValueError):
    """The frame does not hold a dnstap client message this project reads."""


@dataclass(frozen=True, slots=True)
class Record:
    at: datetime
    is_response: bool
    client: ipaddress.IPv4Address | ipaddress.IPv6Address
    port: int
    qname: str
    qtype: str
    # Responses only. A query has no answer to report.
    rcode: str | None
    recursion_available: bool | None


def _at(seconds: int, nanoseconds: int) -> datetime:
    return datetime.fromtimestamp(seconds, UTC) + timedelta(
        microseconds=nanoseconds // 1000
    )


def decode(payload: bytes) -> Record:
    """Decode one frame payload. Raises InvalidMessage for anything else."""
    tap = dnstap_pb2.Dnstap()
    try:
        tap.ParseFromString(payload)
    except (DecodeError, UnicodeDecodeError) as error:
        raise InvalidMessage(f"The frame is not a dnstap message: {error}") from error
    if tap.type != dnstap_pb2.Dnstap.MESSAGE:
        raise InvalidMessage(f"The frame carries type {tap.type}, not a message.")

    message = tap.message
    if message.type not in KEEP:
        raise InvalidMessage(f"{Message.Type.Name(message.type)} is not a client type.")
    is_response = message.type == CLIENT_RESPONSE

    wire = message.response_message if is_response else message.query_message
    if not wire:
        raise InvalidMessage("The message carries no DNS payload.")
    try:
        # question_only stops the parse after the question section. It gives the
        # header flags and the question, which is everything the log shows, and
        # it cannot fail on a record type dnspython does not know. The cost is
        # the EDNS extended rcode bits, which live in the OPT record. Those name
        # BADVERS and friends, never NOERROR or NXDOMAIN.
        answer = dns.message.from_wire(wire, question_only=True, ignore_trailing=True)
    except dns.exception.DNSException as error:
        raise InvalidMessage(f"The DNS payload does not parse: {error}") from error
    if not answer.question:
        raise InvalidMessage("The DNS payload carries no question.")
    question = answer.question[0]

    if is_response:
        seconds, nanoseconds = message.response_time_sec, message.response_time_nsec
    else:
        seconds, nanoseconds = message.query_time_sec, message.query_time_nsec

    return Record(
        at=_at(seconds, nanoseconds),
        is_response=is_response,
        # query_address is the client for both client types. unbound fills it
        # from the query socket.
        client=ipaddress.ip_address(message.query_address),
        port=message.query_port,
        qname=question.name.to_text(omit_final_dot=True).lower(),
        qtype=dns.rdatatype.to_text(question.rdtype),
        rcode=dns.rcode.to_text(answer.rcode()) if is_response else None,
        recursion_available=bool(answer.flags & dns.flags.RA) if is_response else None,
    )
