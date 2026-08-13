"""Decoded against the capture, never against a message written here.

These assertions count and shape. They never print a domain, because the
capture is real traffic.
"""

from collections import Counter
from datetime import UTC, datetime

import pytest

from dnsrules.unbound.dnstap import InvalidMessage, Record, decode
from dnsrules.unbound.framestream import read


@pytest.fixture(scope="session")
def records(dnstap_capture):
    return [decode(frame) for frame in read([dnstap_capture])]


def test_every_frame_in_the_capture_decodes(records):
    assert len(records) > 1
    assert all(isinstance(record, Record) for record in records)


def test_the_capture_holds_queries_and_responses(records):
    kinds = Counter(record.is_response for record in records)
    assert kinds[True] > 0
    assert kinds[False] > 0


def test_every_record_names_a_client_and_a_question(records):
    """Counts, not records. A failed assertion must not print real traffic."""
    complete = [
        record
        for record in records
        if record.qname and record.qtype and 0 < record.port <= 65535
    ]
    assert len(complete) == len(records)


def test_no_name_ends_in_a_dot(records):
    """The rules table stores names without the root dot. Both sides must match."""
    assert sum(record.qname.endswith(".") for record in records) == 0


def test_the_times_are_recent_and_ordered(records):
    """A wrong field or a wrong unit shows up as 1970 or as the far future."""
    first, last = records[0].at, records[-1].at
    assert datetime(2025, 1, 1, tzinfo=UTC) < first < datetime(2100, 1, 1, tzinfo=UTC)
    assert first <= last
    # One capture is a few seconds of traffic.
    assert (last - first).total_seconds() < 3600


def test_only_responses_carry_an_answer(records):
    for record in records:
        if record.is_response:
            assert record.rcode is not None
            assert record.recursion_available is not None
        else:
            assert record.rcode is None
            assert record.recursion_available is None


def test_the_client_addresses_parse(records):
    """Tailnet clients live in 100.64.0.0/10, which is not `is_private`."""
    addresses = [record.client for record in records if record.client.version in (4, 6)]
    assert len(addresses) == len(records)


def test_the_rcodes_are_known(records):
    assert set(record.rcode for record in records if record.is_response) <= {
        "NOERROR",
        "NXDOMAIN",
        "SERVFAIL",
        "REFUSED",
        "NOTIMP",
        "FORMERR",
    }


def test_a_frame_that_is_not_protobuf_is_refused():
    with pytest.raises(InvalidMessage):
        decode(b"\xff\xff\xff\xff not protobuf")


def test_an_empty_frame_is_refused():
    with pytest.raises(InvalidMessage):
        decode(b"")
