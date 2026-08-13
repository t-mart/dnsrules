"""Decoded against the capture, never against a message written here.

These assertions count and shape. They never print a domain, because the
capture is real traffic.
"""

import ipaddress
from collections import Counter
from datetime import UTC, datetime, timedelta

import pytest

from dnsrules.unbound.dnstap import InvalidMessage, Record, decode, pair
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


@pytest.fixture(scope="session")
def exchanges(records):
    return list(pair(records))


def test_pairing_accounts_for_every_query(records, exchanges):
    """One exchange for each query, plus one for any answer that had none."""
    queries = sum(1 for record in records if not record.is_response)
    answers = sum(1 for record in records if record.is_response)
    orphans = sum(1 for e in exchanges if e.reply_ms is None and e.rcode is not None)
    assert len(exchanges) == queries + orphans
    assert sum(1 for e in exchanges if e.rcode is not None) == answers


def test_reply_times_are_sane(records, exchanges):
    times = [e.reply_ms for e in exchanges if e.reply_ms is not None]
    assert times
    assert all(0 <= reply_ms < 10_000 for reply_ms in times)


def test_the_blocked_signal_matches_the_cleared_ra_bit(records, exchanges):
    cleared = sum(
        1 for record in records if record.is_response and not record.recursion_available
    )
    assert sum(1 for e in exchanges if e.blocked) == cleared


def make(at, is_response, port=1000, qname="example.com", qtype="A", ra=True):
    return Record(
        at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=at),
        is_response=is_response,
        client=ipaddress.ip_address("10.0.0.2"),
        port=port,
        qname=qname,
        qtype=qtype,
        rcode="NXDOMAIN" if is_response else None,
        recursion_available=ra if is_response else None,
    )


def test_a_repeated_key_pairs_oldest_first():
    """Clients reuse a source port, so one key holds several open queries."""
    stream = [make(0, False), make(1, False), make(2, True), make(4, True)]
    assert [e.reply_ms for e in pair(stream)] == [2000, 3000]


def test_a_query_with_no_answer_is_yielded_after_the_timeout():
    stream = [make(0, False), make(30, False, port=1001)]
    first, second = pair(stream)
    assert first.reply_ms is None
    assert first.rcode is None
    assert second.rcode is None


def test_an_answer_with_no_query_still_makes_a_row():
    (only,) = pair([make(0, True)])
    assert only.rcode == "NXDOMAIN"
    assert only.reply_ms is None


def test_blocked_needs_both_nxdomain_and_a_cleared_ra_bit():
    (blocked,) = pair([make(0, True, ra=False)])
    (missing,) = pair([make(0, True, ra=True)])
    assert blocked.blocked is True
    assert missing.blocked is False
