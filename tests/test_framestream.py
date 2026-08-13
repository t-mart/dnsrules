"""The captured stream carries the real format. Everything else is a guess.

`test_reads_the_capture` is the only test here that proves the reader matches
unbound. The rest build frames by hand, which tests the reader against this
file's own assumptions. That is worth doing for cases a capture cannot reach,
such as a truncated tail, and worth nothing on its own.

The capture is gitignored, so those tests skip on a machine without one.
"""

import struct

import pytest

from dnsrules.unbound.framestream import (
    DNSTAP_CONTENT_TYPE,
    Control,
    InvalidStream,
    read,
)


def control(kind, content=None):
    payload = struct.pack("!I", kind)
    if content is not None:
        payload += struct.pack("!II", 1, len(content)) + content
    return struct.pack("!II", 0, len(payload)) + payload


def data(payload):
    return struct.pack("!I", len(payload)) + payload


START = control(Control.START, DNSTAP_CONTENT_TYPE)


def test_reads_the_capture(dnstap_capture):
    frames = list(read([dnstap_capture]))
    assert len(frames) > 1
    assert all(frames)


def test_reads_the_capture_in_awkward_chunks(dnstap_capture):
    """A socket splits frames wherever it likes. Chunk edges must not matter."""
    pieces = [dnstap_capture[at : at + 7] for at in range(0, len(dnstap_capture), 7)]
    assert list(read(pieces)) == list(read([dnstap_capture]))


def test_yields_each_data_frame_and_drops_the_control_frame():
    stream = START + data(b"one") + data(b"two")
    assert list(read([stream])) == [b"one", b"two"]


def test_joins_a_frame_that_spans_two_chunks():
    stream = START + data(b"payload")
    assert list(read([stream[:6], stream[6:]])) == [b"payload"]


def test_reads_one_byte_at_a_time():
    stream = START + data(b"one") + data(b"two")
    assert list(read(bytes([byte]) for byte in stream)) == [b"one", b"two"]


def test_an_unknown_control_type_is_ignored():
    """The specification says a receiver ignores a type it does not know."""
    stream = control(99) + data(b"one")
    assert list(read([stream])) == [b"one"]


def test_a_stop_frame_ends_nothing_and_carries_no_content_type():
    stream = START + data(b"one") + control(Control.STOP)
    assert list(read([stream])) == [b"one"]


def test_another_content_type_is_refused():
    stream = control(Control.START, b"protobuf:something.Else")
    with pytest.raises(InvalidStream, match="not dnstap"):
        list(read([stream]))


def test_a_truncated_frame_is_an_error():
    """Ctrl-C during a capture ends the file inside a frame."""
    stream = START + data(b"payload")
    with pytest.raises(InvalidStream, match="ends inside a frame"):
        list(read([stream[:-3]]))


def test_a_frame_longer_than_the_cap_is_refused():
    with pytest.raises(InvalidStream, match="claims"):
        list(read([struct.pack("!I", 1 << 30)]))
