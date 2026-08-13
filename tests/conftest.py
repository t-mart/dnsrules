import pytest

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


@pytest.fixture
def ansible_zone():
    return ANSIBLE_ZONE


@pytest.fixture
def zone_path(tmp_path):
    path = tmp_path / "rpz-runtime-rules.zone"
    path.write_text(ANSIBLE_ZONE)
    return path


@pytest.fixture
def zone_settings(settings, zone_path):
    """Point dnsrules at a throwaway zone file, with no unbound to reload."""
    settings.UNBOUND_ZONE_PATH = zone_path
    settings.UNBOUND_ZONE_MODE = 0o644
    settings.UNBOUND_CONTROL_SOCKET = ""
    return settings


def rules_in(text):
    """Return the rule lines of a rendered zone, without the header."""
    marker = "; block, answer NXDOMAIN\n"
    body = text[text.index(marker) + len(marker) :]
    return [line for line in body.splitlines() if line.strip()]
