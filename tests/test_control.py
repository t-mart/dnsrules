import shutil
import socket
import tempfile
import threading
from pathlib import Path

import pytest

from dnsrules.unbound.control import VERSION, ControlError, auth_zone_reload, command


class FakeUnbound:
    """A unix socket that answers one command, the way unbound does.

    A reply of None accepts the connection and then says nothing, which is what
    a wedged server looks like.
    """

    def __init__(self, reply="ok\n"):
        self.reply = reply
        self.received = None
        self._done = threading.Event()
        self.directory = tempfile.mkdtemp()
        self.path = Path(self.directory) / "control.sock"
        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(self.path))
        self._server.listen(1)
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
        shutil.rmtree(self.directory, ignore_errors=True)


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


def test_auth_zone_reload_sends_the_protocol_line(unbound):
    server = unbound()
    assert auth_zone_reload(server.path, "runtime_rules") == "ok\n"
    assert server.received == f"{VERSION} auth_zone_reload runtime_rules\n"


def test_command_raises_on_an_error_reply(unbound):
    server = unbound("error no auth-zone runtime_rules\n")
    with pytest.raises(ControlError, match="no auth-zone"):
        auth_zone_reload(server.path, "runtime_rules")


def test_command_raises_when_the_socket_is_absent(tmp_path):
    missing = tmp_path / "control.sock"
    with pytest.raises(ControlError, match=r"control\.sock"):
        auth_zone_reload(missing, "runtime_rules")


def test_command_raises_when_unbound_never_answers(unbound):
    server = unbound(reply=None)
    with pytest.raises(ControlError):
        auth_zone_reload(server.path, "runtime_rules", timeout=0.2)


def test_command_refuses_a_newline_before_it_connects(tmp_path):
    """A newline in the command text would smuggle in a second command."""
    with pytest.raises(ControlError, match="newline"):
        command(tmp_path / "control.sock", "auth_zone_reload x\nstop")
