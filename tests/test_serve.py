import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


def test_more_than_one_worker_needs_a_secret_key(monkeypatch):
    """Each worker would generate its own, and reject the other's sessions."""
    monkeypatch.delenv("DNSRULES_SECRET_KEY", raising=False)
    with pytest.raises(CommandError, match="DNSRULES_SECRET_KEY"):
        call_command("serve", "--workers", "2")


def test_secret_prints_a_line_for_the_environment_file(capsys):
    call_command("secret")
    name, _, value = capsys.readouterr().out.strip().partition("=")
    assert name == "DNSRULES_SECRET_KEY"
    assert len(value) > 40
