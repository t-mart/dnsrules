import socket
import threading

import pytest

from dnsrules.unbound.control import (
    VERSION,
    ControlError,
    auth_zone_transfer,
    auth_zones,
    command,
    parse_auth_zones,
)

# Real output from unbound 1.26.0. The name carries a trailing dot, and a zone
# it never fetched says "no serial" rather than zero.
LIST_AUTH_ZONES = (
    "test_feed.\tserial 1\t since 1786684178 2026-08-14T05:09:38\n"
    "runtime_rules.\tno serial\n"
)


class FakeUnbound:
    """A TCP listener that answers one command, the way unbound does.

    A reply of None accepts the connection and then says nothing, which is what
    a wedged server looks like.
    """

    def __init__(self, reply="ok\n"):
        self.reply = reply
        self.received = None
        self._done = threading.Event()
        self._server = socket.create_server(("127.0.0.1", 0))
        self.host, self.port = self._server.getsockname()[:2]
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        try:
            connection, _ = self._server.accept()
        except OSError:
            return
        with connection:
            self.received = connection.recv(4096).decode()
            if self.reply is None:
                self._done.wait(timeout=5)
                return
            connection.sendall(self.reply.encode())

    def close(self):
        self._done.set()
        self._server.close()
        self._thread.join(timeout=5)


@pytest.fixture
def unbound():
    servers = []

    def make(reply="ok\n"):
        server = FakeUnbound(reply)
        servers.append(server)
        return server

    yield make
    for server in servers:
        server.close()


@pytest.fixture
def closed_port():
    """A port nothing listens on. Bound, read for its number, then released."""
    with socket.create_server(("127.0.0.1", 0)) as probe:
        return probe.getsockname()[1]


def test_auth_zone_transfer_sends_the_protocol_line(unbound):
    server = unbound()
    assert auth_zone_transfer(server.host, server.port, "runtime_rules") == "ok\n"
    assert server.received == f"{VERSION} auth_zone_transfer runtime_rules\n"


def test_command_raises_on_an_error_reply(unbound):
    server = unbound("error no auth-zone runtime_rules\n")
    with pytest.raises(ControlError, match="no auth-zone"):
        auth_zone_transfer(server.host, server.port, "runtime_rules")


def test_command_raises_when_nothing_listens(closed_port):
    with pytest.raises(ControlError, match=str(closed_port)):
        auth_zone_transfer("127.0.0.1", closed_port, "runtime_rules")


def test_command_raises_when_unbound_never_answers(unbound):
    server = unbound(reply=None)
    with pytest.raises(ControlError):
        auth_zone_transfer(server.host, server.port, "runtime_rules", timeout=0.2)


def test_parse_auth_zones_reads_a_serial_and_the_lack_of_one():
    assert parse_auth_zones(LIST_AUTH_ZONES) == {"test_feed": 1, "runtime_rules": None}


def test_parse_auth_zones_of_a_resolver_holding_nothing():
    assert parse_auth_zones("") == {}


def test_auth_zones_sends_the_protocol_line(unbound):
    server = unbound(LIST_AUTH_ZONES)
    assert auth_zones(server.host, server.port) == {
        "test_feed": 1,
        "runtime_rules": None,
    }
    assert server.received == f"{VERSION} list_auth_zones\n"


def test_command_refuses_a_newline_before_it_connects(closed_port):
    """A newline in the command text would smuggle in a second command."""
    with pytest.raises(ControlError, match="newline"):
        command("127.0.0.1", closed_port, "auth_zone_transfer x\nstop")
