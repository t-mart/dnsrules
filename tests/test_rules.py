from datetime import timedelta

import pytest
from conftest import rules_in
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone

from dnsrules.rules import services
from dnsrules.rules.models import Rule, Source
from dnsrules.unbound.control import ControlError
from dnsrules.unbound.domain import InvalidDomain
from dnsrules.unbound.zone import Action

pytestmark = pytest.mark.django_db


def make(domain, action=Action.BLOCK, expires_at=None):
    return Rule.objects.create(domain=domain, action=action, expires_at=expires_at)


def test_save_normalizes_the_domain():
    rule = make("  WWW.Example.COM.  ")
    rule.refresh_from_db()
    assert rule.domain == "www.example.com"


def test_save_refuses_a_domain_that_would_not_render():
    with pytest.raises(InvalidDomain):
        make("example.com CNAME rpz-passthru.")


def test_clean_reports_a_bad_domain_as_a_field_error():
    rule = Rule(domain="not a domain")
    with pytest.raises(ValidationError) as caught:
        rule.clean()
    assert "domain" in caught.value.error_dict


def test_a_domain_holds_one_rule():
    make("example.com")
    with pytest.raises(IntegrityError):
        make("example.com")


def test_active_excludes_expired_rules():
    now = timezone.now()
    make("permanent.example.com")
    make("future.example.com", expires_at=now + timedelta(minutes=5))
    make("past.example.com", expires_at=now - timedelta(minutes=5))
    assert [rule.domain for rule in Rule.objects.active()] == [
        "future.example.com",
        "permanent.example.com",
    ]
    assert [rule.domain for rule in Rule.objects.expired()] == ["past.example.com"]


def test_defaults_are_a_permanent_manual_block():
    rule = make("example.com")
    assert rule.action == Action.BLOCK
    assert rule.source == Source.MANUAL
    assert rule.expires_at is None
    assert rule.is_expired is False


def test_reconcile_writes_every_active_rule(zone_settings):
    make("block.example.com", Action.BLOCK)
    make("allow.example.com", Action.ALLOW)
    make("nodata.example.com", Action.BLOCK_NODATA)
    make("gone.example.com", expires_at=timezone.now() - timedelta(minutes=1))

    text = services.reconcile()

    assert rules_in(text) == [
        "allow.example.com CNAME rpz-passthru.",
        "block.example.com CNAME .",
        "nodata.example.com CNAME *.",
    ]
    assert zone_settings.UNBOUND_ZONE_PATH.read_text() == text


def test_reconcile_keeps_the_ansible_header(zone_settings, ansible_zone):
    make("example.com")
    text = services.reconcile()
    assert text.startswith(ansible_zone.rstrip("\n"))


def test_reconcile_with_no_rules_writes_the_header_alone(zone_settings):
    text = services.reconcile()
    assert rules_in(text) == []


def test_reconcile_is_idempotent(zone_settings):
    make("example.com")
    assert services.reconcile() == services.reconcile()


def test_reconcile_skips_the_reload_when_no_socket_is_set(zone_settings, caplog):
    make("example.com")
    services.reconcile()
    assert "skipped" in caplog.text


def test_reconcile_reloads_when_a_socket_is_set(zone_settings, monkeypatch):
    calls = []
    monkeypatch.setattr(
        services.control,
        "auth_zone_reload",
        lambda path, name: calls.append((str(path), name)),
    )
    zone_settings.UNBOUND_CONTROL_SOCKET = "/run/unbound/control.sock"
    make("example.com")
    services.reconcile()
    assert calls == [("/run/unbound/control.sock", "runtime_rules")]


def test_reconcile_reports_a_failed_reload(zone_settings, monkeypatch):
    def boom(path, name):
        raise ControlError("connection refused")

    monkeypatch.setattr(services.control, "auth_zone_reload", boom)
    zone_settings.UNBOUND_CONTROL_SOCKET = "/run/unbound/control.sock"
    make("example.com")
    with pytest.raises(ControlError):
        services.reconcile()
    # The file is already written. The next reconcile converges the two.
    assert "example.com CNAME ." in zone_settings.UNBOUND_ZONE_PATH.read_text()


def test_reconcile_leaves_the_file_alone_when_the_read_fails(
    zone_settings, ansible_zone, monkeypatch
):
    """An empty render would silently drop every rule."""
    make("example.com")
    services.reconcile()
    written = zone_settings.UNBOUND_ZONE_PATH.read_text()

    def boom(*args, **kwargs):
        raise OSError("the database is unreachable")

    monkeypatch.setattr(services.Rule.objects, "active", boom)
    with pytest.raises(OSError, match="unreachable"):
        services.reconcile()
    assert zone_settings.UNBOUND_ZONE_PATH.read_text() == written


def test_prune_deletes_expired_rules_and_rewrites(zone_settings):
    make("keep.example.com")
    make("drop.example.com", expires_at=timezone.now() - timedelta(minutes=1))

    assert services.prune() == 1

    assert rules_in(zone_settings.UNBOUND_ZONE_PATH.read_text()) == [
        "keep.example.com CNAME ."
    ]


def test_prune_with_nothing_to_do_leaves_the_file_untouched(zone_settings):
    make("keep.example.com")
    services.reconcile()
    before = zone_settings.UNBOUND_ZONE_PATH.stat().st_mtime_ns
    assert services.prune() == 0
    assert zone_settings.UNBOUND_ZONE_PATH.stat().st_mtime_ns == before
