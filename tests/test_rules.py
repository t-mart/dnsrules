import io
from datetime import timedelta

import pytest
import yaml
from conftest import rules_in
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError
from django.utils import timezone

from dnsrules.hosts import InvalidHosts
from dnsrules.rules import services
from dnsrules.rules.models import Group, Rule, Source
from dnsrules.unbound.control import ControlError
from dnsrules.unbound.domain import InvalidDomain
from dnsrules.unbound.zone import Action

pytestmark = pytest.mark.django_db


@pytest.fixture
def kids():
    return Group.objects.create(name="kids")


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
    adults = Group.objects.create(name="adults")
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


def test_reconcile_creates_a_row_for_each_group(zone_settings):
    services.reconcile()
    assert [group.name for group in Group.objects.all()] == ["adults", "kids"]


def test_reconcile_writes_each_group_to_its_own_file(zone_settings, zone_files):
    services.reconcile()
    kids, adults = Group.objects.get(name="kids"), Group.objects.get(name="adults")
    make(kids, "block.example.com", Action.BLOCK)
    make(kids, "allow.example.com", Action.ALLOW)
    make(adults, "nodata.example.com", Action.BLOCK_NODATA)
    make(kids, "gone.example.com", expires_at=timezone.now() - timedelta(minutes=1))

    written = services.reconcile()

    assert rules_in(written["kids"]) == [
        "allow.example.com CNAME rpz-passthru.",
        "block.example.com CNAME .",
    ]
    assert rules_in(written["adults"]) == ["nodata.example.com CNAME *."]
    assert zone_files["kids"].read_text() == written["kids"]
    assert zone_files["adults"].read_text() == written["adults"]


def test_reconcile_keeps_the_ansible_header(zone_settings, ansible_zone):
    written = services.reconcile()
    make(Group.objects.get(name="kids"), "example.com")
    written = services.reconcile()
    assert written["kids"].startswith(ansible_zone.rstrip("\n"))


def test_reconcile_with_no_rules_writes_the_header_alone(zone_settings):
    assert rules_in(services.reconcile()["kids"]) == []


def test_reconcile_is_idempotent(zone_settings):
    services.reconcile()
    make(Group.objects.get(name="kids"), "example.com")
    assert services.reconcile() == services.reconcile()


def test_reconcile_skips_a_group_that_left_the_file(zone_settings, caplog):
    make(Group.objects.create(name="guests"), "example.com")
    written = services.reconcile()
    assert "guests" not in written
    assert "guests" in caplog.text
    assert "stale" in caplog.text


def test_stale_groups_reads_the_file(zone_settings):
    guests = Group.objects.create(name="guests")
    services.reconcile()
    entries = services.read_hosts()
    assert list(services.stale_groups(entries)) == [guests]


def test_reconcile_refuses_to_run_without_a_hosts_file(zone_settings, tmp_path):
    zone_settings.HOSTS_PATH = tmp_path / "missing.yml"
    with pytest.raises(InvalidHosts):
        services.reconcile()


def test_reconcile_skips_the_reload_when_no_socket_is_set(zone_settings, caplog):
    services.reconcile()
    assert "skipped" in caplog.text


def test_reconcile_reloads_every_zone_when_a_socket_is_set(zone_settings, monkeypatch):
    calls = []
    monkeypatch.setattr(
        services.control,
        "auth_zone_reload",
        lambda path, name: calls.append((str(path), name)),
    )
    zone_settings.UNBOUND_CONTROL_SOCKET = "/run/unbound/control.sock"
    services.reconcile()
    assert calls == [
        ("/run/unbound/control.sock", "rules_kids"),
        ("/run/unbound/control.sock", "rules_adults"),
    ]


def test_reconcile_reports_a_failed_reload(zone_settings, zone_files, monkeypatch):
    services.reconcile()
    make(Group.objects.get(name="kids"), "example.com")

    def boom(path, name):
        raise ControlError("connection refused")

    monkeypatch.setattr(services.control, "auth_zone_reload", boom)
    zone_settings.UNBOUND_CONTROL_SOCKET = "/run/unbound/control.sock"
    with pytest.raises(ControlError):
        services.reconcile()
    # The file is already written. The next reconcile converges the two.
    assert "example.com CNAME ." in zone_files["kids"].read_text()


def test_reconcile_leaves_the_files_alone_when_the_read_fails(
    zone_settings, zone_files, monkeypatch
):
    """An empty render would silently drop every rule."""
    services.reconcile()
    make(Group.objects.get(name="kids"), "example.com")
    services.reconcile()
    written = zone_files["kids"].read_text()

    def boom(*args, **kwargs):
        raise OSError("the database is unreachable")

    monkeypatch.setattr(services.Rule.objects, "active", boom)
    with pytest.raises(OSError, match="unreachable"):
        services.reconcile()
    assert zone_files["kids"].read_text() == written


def test_prune_deletes_expired_rules_and_rewrites(zone_settings, zone_files):
    services.reconcile()
    kids = Group.objects.get(name="kids")
    make(kids, "keep.example.com")
    make(kids, "drop.example.com", expires_at=timezone.now() - timedelta(minutes=1))

    assert services.prune() == 1

    assert rules_in(zone_files["kids"].read_text()) == ["keep.example.com CNAME ."]


def test_prune_with_nothing_to_do_leaves_the_files_untouched(zone_settings, zone_files):
    services.reconcile()
    make(Group.objects.get(name="kids"), "keep.example.com")
    services.reconcile()
    before = zone_files["kids"].stat().st_mtime_ns
    assert services.prune() == 0
    assert zone_files["kids"].stat().st_mtime_ns == before


def export(**options):
    out = io.StringIO()
    call_command("export", stdout=out, **options)
    return out.getvalue()


def test_export_writes_yaml_by_default(zone_settings):
    services.reconcile()
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
    services.reconcile()
    make(Group.objects.get(name="kids"), "ads.example.com")
    text = export(format="json")
    assert text.lstrip().startswith("[")
    assert yaml.safe_load(text) == yaml.safe_load(export())
