from pathlib import Path

import pytest
import yaml

# Real bytes from mace. Never committed: the capture holds every DNS query the
# house made during its window, which is a browsing history. .gitignore lists
# it, and the tests that need it skip when it is absent.
CAPTURE = Path(__file__).parent / "fixtures" / "dnstap.fstrm"

# Copied from the "Create the runtime rules zone if absent" task in mace's
# playbook.yml. That task runs once, with force: false, so this is the header
# dnsrules reads back on every render.
ANSIBLE_ZONE = """\
$TTL 3600
@ SOA localhost. root.localhost. 1 14400 3600 86400 3600
  NS  localhost.

; Runtime state. Ansible creates this file once and never rewrites it.
; This zone is read first, so a rule here beats every other RPZ zone.
;
; Format:
; <domain> CNAME rpz-passthru.   ; ignore the blocklist
; <domain> CNAME .               ; block, answer NXDOMAIN
"""

GROUPS = ("kids", "adults")


@pytest.fixture
def ansible_zone():
    return ANSIBLE_ZONE


@pytest.fixture
def zone_path(tmp_path):
    path = tmp_path / "rpz-runtime-rules.zone"
    path.write_text(ANSIBLE_ZONE)
    return path


@pytest.fixture
def zone_files(tmp_path):
    """One zone file for each group, as Ansible creates them: header only."""
    files = {}
    for name in GROUPS:
        files[name] = tmp_path / f"{name}.zone"
        files[name].write_text(ANSIBLE_ZONE)
    return files


@pytest.fixture
def hosts_path(tmp_path, zone_files):
    path = tmp_path / "hosts.yml"
    path.write_text(
        yaml.safe_dump(
            {
                "groups": [
                    {
                        "name": name,
                        "zone": f"rules_{name}",
                        "zonefile": str(zone_files[name]),
                    }
                    for name in GROUPS
                ],
                "hosts": [
                    {
                        "name": "clove",
                        "addresses": ["10.0.0.2", "100.71.4.9"],
                        "groups": ["kids"],
                    }
                ],
            }
        )
    )
    return path


@pytest.fixture
def zone_settings(settings, hosts_path):
    """Point dnsrules at a throwaway hosts.yml, with no unbound to reload."""
    settings.HOSTS_PATH = hosts_path
    settings.UNBOUND_ZONE_MODE = 0o644
    settings.UNBOUND_CONTROL_SOCKET = ""
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
    marker = "; block, answer NXDOMAIN\n"
    body = text[text.index(marker) + len(marker) :]
    return [line for line in body.splitlines() if line.strip()]
