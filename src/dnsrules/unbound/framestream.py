"""Frame Streams, the envelope unbound wraps around each dnstap message.

The format, from `fstrm/control.h` by way of unbound's `dnstap_fstrm.h`:

    data frame:    4 byte big-endian length, then that many bytes
    control frame: 4 zero bytes, then a 4 byte length, then the payload

A zero length is the escape that marks a control frame. A data frame is never
empty, so the escape is unambiguous.

A control payload starts with a 4 byte type. START, READY and ACCEPT carry one
field: the content type string. STOP and FINISH carry nothing. The specification
says a receiver ignores a type it does not know.

This module reads. It never writes. unbound is the only sender.
"""

import enum
import struct
from collections.abc import Iterable, Iterator

LENGTH = struct.Struct("!I")
ESCAPE = 0

CONTENT_TYPE_FIELD = 1
DNSTAP_CONTENT_TYPE = b"protobuf:dnstap.Dnstap"

# unbound's frames run to about 500 bytes. The cap stops a wrong length from
# growing the buffer without limit.
MAX_FRAME = 1 << 20


class Control(enum.IntEnum):
    ACCEPT = 1
    START = 2
    STOP = 3
    READY = 4
    FINISH = 5


# The three types that name the content of the stream.
NAMES_CONTENT = frozenset({Control.ACCEPT, Control.START, Control.READY})


class InvalidStream(ValueError):
    """The bytes do not form a dnstap frame stream."""


def _content_type(fields: bytes) -> bytes | None:
    """Return the content type string, or None when the frame carries none."""
    while len(fields) >= 2 * LENGTH.size:
        (kind,) = LENGTH.unpack_from(fields)
        (size,) = LENGTH.unpack_from(fields, LENGTH.size)
        start = 2 * LENGTH.size
        if len(fields) < start + size:
            raise InvalidStream("A control field runs past the end of its frame.")
        if kind == CONTENT_TYPE_FIELD:
            return fields[start : start + size]
        fields = fields[start + size :]
    return None


def _check_control(payload: bytes) -> None:
    if len(payload) < LENGTH.size:
        raise InvalidStream("A control frame carries no type.")
    (kind,) = LENGTH.unpack_from(payload)
    if kind not in NAMES_CONTENT:
        return
    content = _content_type(payload[LENGTH.size :])
    if content is not None and content != DNSTAP_CONTENT_TYPE:
        raise InvalidStream(f"The stream carries {content!r}, not dnstap.")


def read(chunks: Iterable[bytes]) -> Iterator[bytes]:
    """Yield each data frame payload, in order.

    Takes byte chunks, so one reader serves a file and a socket alike. A frame
    that spans two chunks is joined. Control frames are checked and dropped.

    Raises InvalidStream when the input ends inside a frame. A capture stopped
    with Ctrl-C can end that way, and so can a sender that died.
    """
    buffer = bytearray()
    for chunk in chunks:
        buffer += chunk
        while True:
            if len(buffer) < LENGTH.size:
                break
            (length,) = LENGTH.unpack_from(buffer)
            start = LENGTH.size
            control = length == ESCAPE
            if control:
                if len(buffer) < 2 * LENGTH.size:
                    break
                (length,) = LENGTH.unpack_from(buffer, LENGTH.size)
                start = 2 * LENGTH.size
            if length > MAX_FRAME:
                raise InvalidStream(f"A frame claims {length} bytes.")
            end = start + length
            if len(buffer) < end:
                break
            frame = bytes(buffer[start:end])
            del buffer[:end]
            if control:
                _check_control(frame)
            else:
                yield frame
    if buffer:
        raise InvalidStream(f"The input ends inside a frame, {len(buffer)} bytes in.")
