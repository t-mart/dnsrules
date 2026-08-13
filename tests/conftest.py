import pytest
import yaml

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
def inventory_path(tmp_path, zone_files):
    path = tmp_path / "inventory.yml"
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
def zone_settings(settings, inventory_path):
    """Point dnsrules at a throwaway inventory, with no unbound to reload."""
    settings.INVENTORY_PATH = inventory_path
    settings.UNBOUND_ZONE_MODE = 0o644
    settings.UNBOUND_CONTROL_SOCKET = ""
    return settings


def rules_in(text):
    """Return the rule lines of a rendered zone, without the header."""
    marker = "; block, answer NXDOMAIN\n"
    body = text[text.index(marker) + len(marker) :]
    return [line for line in body.splitlines() if line.strip()]
