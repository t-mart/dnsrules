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
from collections import defaultdict, deque
from collections.abc import Iterable, Iterator
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


@dataclass(frozen=True, slots=True)
class Exchange:
    """One row of the query log: a question and what came back."""

    at: datetime
    client: ipaddress.IPv4Address | ipaddress.IPv6Address
    qname: str
    qtype: str
    # None when no answer arrived inside the window.
    rcode: str | None
    recursion_available: bool | None
    reply_ms: float | None

    @property
    def blocked(self) -> bool:
        """The in-band signal, from `rpz-signal-nxdomain-ra: yes`.

        A policy answer clears RA. A name that truly does not exist keeps it.
        The journal names which zone acted. This is the fallback when that join
        finds nothing.
        """
        return self.rcode == "NXDOMAIN" and self.recursion_available is False


def _key(record: Record) -> tuple:
    return (record.client, record.port, record.qname, record.qtype)


def _exchange(query: Record | None, answer: Record | None) -> Exchange:
    first = query or answer
    assert first is not None
    reply_ms = None
    if query is not None and answer is not None:
        reply_ms = (answer.at - query.at).total_seconds() * 1000
    return Exchange(
        at=first.at,
        client=first.client,
        qname=first.qname,
        qtype=first.qtype,
        rcode=answer.rcode if answer else None,
        recursion_available=answer.recursion_available if answer else None,
        reply_ms=reply_ms,
    )


def pair(
    records: Iterable[Record], *, timeout: timedelta = timedelta(seconds=10)
) -> Iterator[Exchange]:
    """Join each query to its answer, and yield one exchange for each.

    unbound stamps a client response with `response_time` and never with
    `query_time`, so reply time exists only across the pair.

    The key is client, port, name, and type. It is not unique: measured on a
    real capture, 108 of 488 keys repeated, some four times. Clients reuse a
    source port. So each key holds a queue, and the oldest query takes the next
    answer. Nothing is overwritten, and every query reaches the log.

    A query with no answer inside `timeout` is yielded alone. The clock comes
    from the records, never from this machine, so a replay gives the same
    result as a live stream.

    Each exchange is stamped with the time the query arrived, so the output
    runs near time order, out by at most `timeout`. That suits a BRIN index.
    """
    waiting: dict[tuple, deque[Record]] = defaultdict(deque)
    # Arrival order, for expiry. A paired query stays here until it ages out,
    # and the head check below skips it.
    arrivals: deque[Record] = deque()

    def expire(deadline: datetime) -> Iterator[Exchange]:
        while arrivals and arrivals[0].at < deadline:
            query = arrivals.popleft()
            queue = waiting.get(_key(query))
            if queue and queue[0] is query:
                queue.popleft()
                if not queue:
                    del waiting[_key(query)]
                yield _exchange(query, None)

    for record in records:
        key = _key(record)
        if record.is_response:
            queue = waiting.get(key)
            query = queue.popleft() if queue else None
            if queue is not None and not queue:
                del waiting[key]
            yield _exchange(query, record)
        else:
            waiting[key].append(record)
            arrivals.append(record)
        yield from expire(record.at - timeout)
    yield from expire(datetime.max.replace(tzinfo=UTC))
