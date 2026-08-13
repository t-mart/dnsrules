import json
import subprocess

import pytest

from dnsrules import names
from dnsrules.hosts import load

STATUS = {
    "Self": {"DNSName": "mace.tail1234.ts.net.", "TailscaleIPs": ["100.71.4.1"]},
    "Peer": {
        "key1": {"DNSName": "phone.tail1234.ts.net.", "TailscaleIPs": ["100.71.4.20"]},
    },
}


@pytest.fixture
def describe(hosts_path):
    return names.directory(load(hosts_path), tailnet_names={})


def test_a_known_address_takes_its_host_name(describe):
    client = describe("10.0.0.2")
    assert client.name == "clove"
    assert client.known is True
    assert client.groups == ("kids",)


def test_every_address_of_a_host_names_it(describe):
    assert describe("100.71.4.9").name == "clove"


def test_an_unknown_address_shows_itself(describe):
    client = describe("10.0.0.99")
    assert client.name == "10.0.0.99"
    assert client.known is False
    assert client.groups == ()


def test_a_client_in_the_dhcp_pool_is_unmanaged(describe):
    """It carries no tag in unbound.conf, so no rule reaches it."""
    client = describe("10.0.1.50")
    assert client.network == "dhcp pool"
    assert client.managed is False


def test_a_client_in_the_lan_is_managed(describe):
    assert describe("10.0.0.2").managed is True


def test_a_client_outside_every_network_is_unmanaged(describe):
    client = describe("192.0.2.1")
    assert client.network == ""
    assert client.managed is False


def test_something_that_is_not_an_address_still_returns(describe):
    assert describe("not an address").name == "not an address"


def test_the_hosts_file_beats_the_tailnet(hosts_path):
    describe = names.directory(load(hosts_path), tailnet_names={"10.0.0.2": "wrong"})
    assert describe("10.0.0.2").name == "clove"


def test_a_tailnet_name_fills_a_gap(hosts_path):
    describe = names.directory(load(hosts_path), tailnet_names={"100.71.4.20": "phone"})
    assert describe("100.71.4.20").name == "phone"


def test_tailnet_reads_the_status_json(monkeypatch):
    monkeypatch.setattr(
        names.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args, 0, stdout=json.dumps(STATUS), stderr=""
        ),
    )
    assert names.tailnet() == {"100.71.4.1": "mace", "100.71.4.20": "phone"}


def test_the_cache_calls_tailscale_once_for_each_bucket(monkeypatch):
    """One subprocess for each time bucket, not one for each page view."""
    calls = []
    monkeypatch.setattr(names, "tailnet", lambda: calls.append(1) or {"a": "b"})
    assert names._bucketed(1) == {"a": "b"}
    assert names._bucketed(1) == {"a": "b"}
    assert names._bucketed(2) == {"a": "b"}
    assert len(calls) == 2


def test_no_tailscale_means_no_tailnet_names(monkeypatch):
    """A development machine has no tailscale, and neither does a test runner."""

    def missing(*args, **kwargs):
        raise FileNotFoundError("tailscale")

    monkeypatch.setattr(names.subprocess, "run", missing)
    assert names.tailnet() == {}
