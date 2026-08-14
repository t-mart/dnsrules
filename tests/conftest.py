from pathlib import Path

import pytest
import yaml

from dnsrules import names
from dnsrules.rules import services

# Real bytes from mace. Never committed: the capture holds every DNS query the
# house made during its window, which is a browsing history. .gitignore lists
# it, and the tests that need it skip when it is absent.
CAPTURE = Path(__file__).parent / "fixtures" / "dnstap.fstrm"

GROUPS = ("kids", "adults")


@pytest.fixture
def hosts_path(tmp_path):
    path = tmp_path / "hosts.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "groups": [{"name": name, "zone": f"rules_{name}"} for name in GROUPS],
                "hosts": [
                    {
                        "name": "clove",
                        "addresses": ["10.0.0.2", "100.71.4.9"],
                        "groups": ["kids"],
                    }
                ],
                "networks": [
                    {"name": "lan", "cidr": "10.0.0.0/24"},
                    {"name": "dhcp pool", "cidr": "10.0.1.0/24", "managed": False},
                    {"name": "tailnet", "cidr": "100.64.0.0/10"},
                ],
            }
        )
    )
    return path


@pytest.fixture
def transfers(monkeypatch):
    """Record each auth_zone_transfer rather than reach a real resolver.

    Returns the list of zone names, in call order.
    """
    calls = []

    def record(host, port, zone, **kwargs):
        calls.append(zone)
        return "ok\n"

    monkeypatch.setattr(services.control, "auth_zone_transfer", record)
    return calls


@pytest.fixture
def zone_settings(settings, hosts_path, transfers):
    """Point dnsrules at a throwaway hosts.yml, with no unbound to tell."""
    settings.HOSTS_PATH = hosts_path
    return settings


@pytest.fixture(autouse=True)
def no_tailscale(monkeypatch):
    """No test shells out. A test that wants tailnet names passes them in."""
    names._bucketed.cache_clear()
    monkeypatch.setattr(names, "cached_tailnet", lambda *args, **kwargs: {})


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
