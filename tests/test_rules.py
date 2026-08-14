import io
from datetime import timedelta

import pytest
import yaml
from conftest import rules_in
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.utils import timezone

from dnsrules.rules import services
from dnsrules.rules.models import Group, Rule, Source
from dnsrules.unbound.control import ControlError
from dnsrules.unbound.domain import InvalidDomain
from dnsrules.unbound.zone import Action

pytestmark = pytest.mark.django_db


@pytest.fixture
def kids(groups):
    return Group.objects.get(name="kids")


def make(group, domain, action=Action.BLOCK, expires_at=None):
    return Rule.objects.create(
        group=group, domain=domain, action=action, expires_at=expires_at
    )


def test_save_normalizes_the_domain(kids):
    rule = make(kids, "  WWW.Example.COM.  ")
    rule.refresh_from_db()
    assert rule.domain == "www.example.com"


def test_save_refuses_a_domain_that_would_not_render(kids):
    with pytest.raises(InvalidDomain):
        make(kids, "example.com CNAME rpz-passthru.")


def test_clean_reports_a_bad_domain_as_a_field_error():
    rule = Rule(domain="not a domain")
    with pytest.raises(ValidationError) as caught:
        rule.clean()
    assert "domain" in caught.value.error_dict


def test_a_domain_holds_one_rule_in_each_group(kids):
    adults = Group.objects.get(name="adults")
    make(kids, "example.com")
    make(adults, "example.com")
    with pytest.raises(IntegrityError):
        make(kids, "example.com")


def test_active_excludes_expired_rules(kids):
    now = timezone.now()
    make(kids, "permanent.example.com")
    make(kids, "future.example.com", expires_at=now + timedelta(minutes=5))
    make(kids, "past.example.com", expires_at=now - timedelta(minutes=5))
    assert [rule.domain for rule in Rule.objects.active()] == [
        "future.example.com",
        "permanent.example.com",
    ]
    assert [rule.domain for rule in Rule.objects.expired()] == ["past.example.com"]


def test_defaults_are_a_permanent_manual_block(kids):
    rule = make(kids, "example.com")
    assert rule.action == Action.BLOCK
    assert rule.source == Source.MANUAL
    assert rule.expires_at is None
    assert rule.is_expired is False


def test_zone_text_holds_only_that_group(zone_settings):
    kids, adults = Group.objects.get(name="kids"), Group.objects.get(name="adults")
    make(kids, "block.example.com", Action.BLOCK)
    make(kids, "allow.example.com", Action.ALLOW)
    make(adults, "nodata.example.com", Action.BLOCK_NODATA)
    make(kids, "gone.example.com", expires_at=timezone.now() - timedelta(minutes=1))

    assert rules_in(services.zone_text(kids)) == [
        "allow.example.com CNAME rpz-passthru.",
        "block.example.com CNAME .",
    ]
    assert rules_in(services.zone_text(adults)) == ["nodata.example.com CNAME *."]


def test_zone_text_with_no_rules_is_the_header_alone(zone_settings):
    assert rules_in(services.zone_text(Group.objects.get(name="kids"))) == []


def test_reconcile_raises_every_serial(zone_settings):
    """unbound takes a transfer only when the serial rises."""
    before = [group.serial for group in Group.objects.order_by("name")]
    services.reconcile()
    after = [group.serial for group in Group.objects.order_by("name")]
    assert after == [serial + 1 for serial in before]


def test_reconcile_tells_unbound_about_every_zone(zone_settings, transfers):
    services.reconcile()
    assert transfers == ["rules_adults", "rules_kids"]


def test_reconcile_raises_the_serial_before_it_asks_for_a_transfer(
    zone_settings, transfers, monkeypatch
):
    """A transfer that arrives before the bump would fetch the old zone."""
    seen = []

    def record(host, port, zone, **kwargs):
        seen.append(Group.objects.get(name="kids").serial)
        return "ok\n"

    monkeypatch.setattr(services.control, "auth_zone_transfer", record)
    services.reconcile()
    services.reconcile()
    assert seen == [2, 2, 3, 3]


def test_reconcile_reports_a_failed_transfer(zone_settings, monkeypatch):
    kids = Group.objects.get(name="kids")
    make(kids, "example.com")

    def boom(host, port, zone, **kwargs):
        raise ControlError("connection refused")

    monkeypatch.setattr(services.control, "auth_zone_transfer", boom)
    with pytest.raises(ControlError):
        services.reconcile()
    # The rule is in the zone already. unbound fetches it at the next refresh.
    assert "example.com CNAME ." in services.zone_text(kids)


def test_prune_deletes_expired_rules_and_tells_unbound(zone_settings, transfers):
    kids = Group.objects.get(name="kids")
    make(kids, "keep.example.com")
    make(kids, "drop.example.com", expires_at=timezone.now() - timedelta(minutes=1))
    transfers.clear()

    assert services.prune() == 1

    assert rules_in(services.zone_text(kids)) == ["keep.example.com CNAME ."]
    assert transfers == ["rules_adults", "rules_kids"]


def test_prune_with_nothing_to_do_tells_unbound_nothing(zone_settings, transfers):
    make(Group.objects.get(name="kids"), "keep.example.com")
    transfers.clear()
    assert services.prune() == 0
    assert transfers == []


def export(**options):
    out = io.StringIO()
    call_command("export", stdout=out, **options)
    return out.getvalue()


def test_export_writes_yaml_by_default(zone_settings):
    make(Group.objects.get(name="kids"), "ads.example.com")
    assert yaml.safe_load(export()) == [
        {
            "group": "kids",
            "domain": "ads.example.com",
            "action": "block",
            "source": "manual",
            "expires_at": None,
            "note": "",
        }
    ]


def test_export_writes_json_when_asked(zone_settings):
    make(Group.objects.get(name="kids"), "ads.example.com")
    text = export(format="json")
    assert text.lstrip().startswith("[")
    assert yaml.safe_load(text) == yaml.safe_load(export())
