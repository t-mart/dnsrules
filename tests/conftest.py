from pathlib import Path

import pytest

from dnsrules.rules import services
from dnsrules.rules.models import Group

# Real bytes from a resolver. Never committed: the capture holds every DNS query
# house made during its window, which is a browsing history. .gitignore lists
# it, and the tests that need it skip when it is absent.
CAPTURE = Path(__file__).parent / "fixtures" / "dnstap.fstrm"


@pytest.fixture
def transfers(monkeypatch):
    """Record each auth_zone_transfer rather than reach a real resolver.

    Returns the list of zone names, in call order.

    `auth_zones` answers as a resolver that took every transfer, because
    reconcile reads the serial back to confirm one landed. A test that wants a
    resolver which did not take it overrides this.
    """
    calls = []

    def record(host, port, zone, **kwargs):
        calls.append(zone)
        return "ok\n"

    def held(host, port, **kwargs):
        return {group.name: group.serial for group in Group.objects.all()}

    monkeypatch.setattr(services.control, "auth_zone_transfer", record)
    monkeypatch.setattr(services.control, "auth_zones", held)
    return calls


@pytest.fixture
def groups(db, settings):
    """Two zones, the way a deploy declares them.

    The zone the app seeds at migrate goes first, so a test that counts zones
    counts only these.
    """
    Group.objects.all().delete()
    settings.RPZ_ZONES = ["adults", "kids"]
    return [
        Group.objects.create(name="adults"),
        Group.objects.create(name="kids"),
    ]


@pytest.fixture
def zone_settings(settings, transfers, groups):
    """Two zones, and no unbound to tell about them."""
    return settings


@pytest.fixture(scope="session")
def dnstap_capture():
    """The captured dnstap stream, or a skip when nobody captured one.

    Skipping is the right answer here. The format belongs to unbound, so a
    stream written by this project would test the reader against its own
    assumptions. Better to run nothing than to run something misleading.

    Make one with the recipe under "Fixtures" in the README.
    """
    if not CAPTURE.is_file():
        pytest.skip(f"No dnstap capture at {CAPTURE}. See 'Fixtures' in the README.")
    return CAPTURE.read_bytes()


def rules_in(text):
    """Return the rule lines of a rendered zone, without the header."""
    return [
        line
        for line in text.splitlines()
        if line.strip() and not line.startswith(("$", "@", ";"))
    ]
