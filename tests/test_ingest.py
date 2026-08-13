import socket
import threading
from datetime import date

import pytest

from dnsrules.queries import partitions
from dnsrules.queries.models import Query
from dnsrules.queries.services import ingest, store
from dnsrules.unbound import receiver
from dnsrules.unbound.dnstap import decode, pair
from dnsrules.unbound.framestream import read

pytestmark = pytest.mark.django_db


@pytest.fixture
def partitioned():
    """Real days, so the capture's rows have somewhere to land."""
    partitions.reconcile(date(2026, 8, 13), ahead=1, keep=3650)


def test_ingest_writes_every_exchange(dnstap_capture, partitioned):
    expected = len(list(pair(decode(frame) for frame in read([dnstap_capture]))))

    written = ingest([dnstap_capture])

    assert written == expected
    assert Query.objects.count() == expected


def test_the_rows_carry_what_the_capture_carried(dnstap_capture, partitioned):
    ingest([dnstap_capture])
    rows = Query.objects.all()
    assert rows.filter(qname="").count() == 0
    assert rows.filter(blocked=True).count() > 0
    assert rows.exclude(reply_ms=None).count() > 0
    # Every row landed in a real partition, not the catch-all one.
    assert partitions.default_rows() == 0


def test_a_query_with_no_answer_stores_an_empty_rcode(dnstap_capture, partitioned):
    ingest([dnstap_capture])
    unanswered = Query.objects.filter(rcode="")
    assert unanswered.count() > 0
    assert unanswered.filter(reply_ms=None).count() == unanswered.count()


def test_ingest_batches_on_the_tick(dnstap_capture, partitioned, monkeypatch):
    """A house makes about three queries a second. Size alone would hold rows."""
    writes = []

    def fake_store(rows):
        writes.append(len(rows))
        return len(rows)

    monkeypatch.setattr("dnsrules.queries.services.store", fake_store)
    ticks = iter(range(1_000_000))
    total = ingest(
        [dnstap_capture], batch=10_000, interval=1.0, clock=lambda: next(ticks)
    )
    assert len(writes) > 1
    assert sum(writes) == total


def test_a_bad_frame_does_not_end_the_stream(dnstap_capture, partitioned, caplog):
    """One unreadable frame must cost one row, never the connection."""
    frames = list(read([dnstap_capture]))
    stream = b"".join(
        len(frame).to_bytes(4, "big") + frame for frame in [b"\xff\xff\xff", *frames]
    )
    written = ingest([stream])
    assert written == len(list(pair(decode(frame) for frame in frames)))
    assert "Skipped a dnstap frame" in caplog.text


def test_store_with_nothing_to_write_touches_nothing():
    assert store([]) == 0


def test_the_receiver_takes_one_connection_after_another():
    """A real socket. unbound connects out, so this side listens."""
    address = []
    ready = threading.Event()
    received = []

    def listening(name):
        address.append(name)
        ready.set()

    def serve():
        for chunks in receiver.connections("127.0.0.1", 0, ready=listening):
            received.append(b"".join(chunks))
            if len(received) == 2:
                return

    server = threading.Thread(target=serve, daemon=True)
    server.start()
    assert ready.wait(timeout=5)

    for payload in (b"first", b"second"):
        with socket.create_connection(address[0], timeout=5) as client:
            client.sendall(payload)
    server.join(timeout=5)

    assert received == [b"first", b"second"]
