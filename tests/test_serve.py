from django.core.management import call_command

from dnsrules.core.management.commands import serve


def test_serve_runs_one_worker_with_the_background_hook(monkeypatch):
    """A second worker would ingest the dnstap stream twice.

    The hook has to run after the fork. A database connection opened before it
    would be shared by two processes.
    """
    captured = {}
    monkeypatch.setattr(
        serve.Application, "run", lambda self: captured.update(self.options)
    )

    call_command("serve")

    assert captured["workers"] == 1
    assert captured["post_worker_init"] is serve._background


def test_secret_prints_a_line_for_the_environment_file(capsys):
    call_command("secret")
    name, _, value = capsys.readouterr().out.strip().partition("=")
    assert name == "DNSRULES_SECRET_KEY"
    assert len(value) > 40
