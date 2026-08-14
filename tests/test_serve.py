from django.core.management import call_command

from dnsrules.core.management.commands import serve


def test_serve_migrates_then_runs_one_worker_with_the_hook(monkeypatch):
    """A second worker would ingest the dnstap stream twice.

    The order matters as much as the count. Migrating opens a connection, and
    gunicorn forks after this, so the connection has to close before the fork
    or two processes share one and corrupt the protocol.
    """
    order = []
    captured = {}
    monkeypatch.setattr(serve, "call_command", lambda name, **kw: order.append(name))
    monkeypatch.setattr(serve.connections, "close_all", lambda: order.append("close"))
    monkeypatch.setattr(
        serve.Application, "run", lambda self: captured.update(self.options)
    )

    call_command("serve")

    assert order == ["migrate", "close"]
    assert captured["workers"] == 1
    assert captured["post_worker_init"] is serve._background


def test_secret_prints_a_line_for_the_environment_file(capsys):
    call_command("secret")
    name, _, value = capsys.readouterr().out.strip().partition("=")
    assert name == "DNSRULES_SECRET_KEY"
    assert len(value) > 40
