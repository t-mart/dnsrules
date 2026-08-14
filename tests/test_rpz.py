"""The endpoint unbound fetches.

It carries no session and takes no authentication, because unbound cannot sign
in. Everything else about it is ordinary.
"""

import pytest
from conftest import rules_in

from dnsrules.rules import services
from dnsrules.rules.models import Group, Rule
from dnsrules.unbound.zone import Action

pytestmark = pytest.mark.django_db


def make(group, domain, action=Action.BLOCK):
    return Rule.objects.create(group=group, domain=domain, action=action)


def test_it_serves_the_zone_without_a_session(client, zone_settings):
    services.reconcile()
    make(Group.objects.get(name="kids"), "ads.example.com")

    response = client.get("/rpz/kids.zone")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert rules_in(response.content.decode()) == ["ads.example.com CNAME ."]


def test_it_carries_the_serial_that_reconcile_raised(client, zone_settings):
    services.reconcile()
    services.reconcile()
    serial = Group.objects.get(name="kids").serial

    body = client.get("/rpz/kids.zone").content.decode()

    assert f"root.localhost. {serial} " in body


def test_a_fetch_does_not_move_the_serial(client, zone_settings):
    """unbound refetches on its own schedule. Only a change moves the serial."""
    services.reconcile()
    before = Group.objects.get(name="kids").serial
    client.get("/rpz/kids.zone")
    assert Group.objects.get(name="kids").serial == before


def test_each_group_gets_its_own_zone(client, zone_settings):
    services.reconcile()
    make(Group.objects.get(name="kids"), "kids.example.com")
    make(Group.objects.get(name="adults"), "adults.example.com")

    kids = client.get("/rpz/kids.zone").content.decode()

    assert rules_in(kids) == ["kids.example.com CNAME ."]


def test_an_unknown_group_is_a_404(client, zone_settings):
    services.reconcile()
    assert client.get("/rpz/nobody.zone").status_code == 404


def test_a_fresh_database_serves_the_configured_zone(client, db, settings):
    """The two names in unbound.conf. A migration seeds them from the settings."""
    zone = Group.objects.get(name=settings.RPZ_NAME)

    assert zone.zone == settings.RPZ_ZONE
    assert client.get(f"/rpz/{settings.RPZ_NAME}.zone").status_code == 200


def test_a_database_fault_never_answers_an_empty_zone(
    client, zone_settings, monkeypatch
):
    """An empty zone would unblock the house. A 500 keeps unbound's copy."""
    services.reconcile()

    def boom(*args, **kwargs):
        raise OSError("the database is unreachable")

    monkeypatch.setattr(services.Rule.objects, "active", boom)
    with pytest.raises(OSError, match="unreachable"):
        client.get("/rpz/kids.zone")
