import pytest
from conftest import rules_in

from dnsrules.rules.models import Group, Rule
from dnsrules.unbound.zone import Action

pytestmark = pytest.mark.django_db

HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def admin(client, django_user_model):
    user = django_user_model.objects.create_user(username="tim", password="secret")
    client.force_login(user)
    return user


def add(client, group, domain, action=Action.BLOCK, duration=""):
    return client.post(
        "/rules/",
        {
            "group": group.pk,
            "domain": domain,
            "action": action,
            "duration": duration,
            "note": "",
        },
        **HTMX,
    )


def test_the_rules_page_needs_a_login(client):
    assert client.get("/rules/").status_code == 302


def test_the_page_lists_a_group_for_each_entry(client, admin, zone_settings):
    body = client.get("/rules/").content.decode()
    assert "kids" in body
    assert "adults" in body


def test_a_visit_gives_every_group_a_row(client, admin, zone_settings):
    client.get("/rules/")
    assert [group.name for group in Group.objects.all()] == ["adults", "kids"]


def test_adding_a_rule_writes_the_zone_file(client, admin, zone_settings, zone_files):
    client.get("/rules/")
    kids = Group.objects.get(name="kids")

    response = add(client, kids, "ads.example.com")

    assert response.status_code == 200
    assert rules_in(zone_files["kids"].read_text()) == ["ads.example.com CNAME ."]


def test_a_duration_sets_the_expiry(client, admin, zone_settings):
    client.get("/rules/")
    kids = Group.objects.get(name="kids")
    add(client, kids, "ads.example.com", duration="3600")
    assert Rule.objects.get().expires_at is not None


def test_a_bad_domain_answers_422_and_writes_nothing(
    client, admin, zone_settings, zone_files
):
    """htmx 4 swaps a 4xx, so the form redisplays with its errors."""
    client.get("/rules/")
    kids = Group.objects.get(name="kids")

    response = add(client, kids, "not a domain")

    assert response.status_code == 422
    assert "is not a domain name" in response.content.decode()
    assert rules_in(zone_files["kids"].read_text()) == []


def test_a_repeated_domain_in_one_group_answers_422(client, admin, zone_settings):
    client.get("/rules/")
    kids = Group.objects.get(name="kids")
    add(client, kids, "ads.example.com")
    assert add(client, kids, "ads.example.com").status_code == 422
    assert Rule.objects.count() == 1


def test_removing_a_rule_rewrites_the_zone_file(
    client, admin, zone_settings, zone_files
):
    client.get("/rules/")
    kids = Group.objects.get(name="kids")
    add(client, kids, "ads.example.com")

    response = client.delete(f"/rules/{Rule.objects.get().pk}/", **HTMX)

    assert response.status_code == 200
    assert Rule.objects.count() == 0
    assert rules_in(zone_files["kids"].read_text()) == []


def test_editing_a_rule_changes_the_action(client, admin, zone_settings, zone_files):
    client.get("/rules/")
    kids = Group.objects.get(name="kids")
    add(client, kids, "ads.example.com")
    rule = Rule.objects.get()

    assert client.get(f"/rules/{rule.pk}/", **HTMX).status_code == 200
    client.post(
        f"/rules/{rule.pk}/",
        {
            "group": kids.pk,
            "domain": "ads.example.com",
            "action": Action.ALLOW,
            "duration": "keep",
            "note": "school project",
        },
        **HTMX,
    )

    assert rules_in(zone_files["kids"].read_text()) == [
        "ads.example.com CNAME rpz-passthru."
    ]
    assert Rule.objects.get().note == "school project"


def test_editing_keeps_the_expiry_when_asked(client, admin, zone_settings):
    client.get("/rules/")
    kids = Group.objects.get(name="kids")
    add(client, kids, "ads.example.com", duration="3600")
    rule = Rule.objects.get()
    before = rule.expires_at

    client.post(
        f"/rules/{rule.pk}/",
        {
            "group": kids.pk,
            "domain": "ads.example.com",
            "action": Action.BLOCK,
            "duration": "keep",
            "note": "",
        },
        **HTMX,
    )

    assert Rule.objects.get().expires_at == before


def test_a_stale_group_is_shown_with_its_rules(client, admin, zone_settings):
    guests = Group.objects.create(name="guests")
    Rule.objects.create(group=guests, domain="ads.example.com")
    body = client.get("/rules/").content.decode()
    assert "guests" in body
    assert "stale" in body


def test_a_stale_group_takes_no_new_rules(client, admin, zone_settings):
    guests = Group.objects.create(name="guests")
    assert add(client, guests, "ads.example.com").status_code == 422
    assert Rule.objects.count() == 0


def test_a_missing_hosts_file_reports_itself(client, admin, zone_settings, tmp_path):
    zone_settings.HOSTS_PATH = tmp_path / "missing.yml"
    response = client.get("/rules/")
    assert response.status_code == 503
    assert "does not exist" in response.content.decode()


def test_a_failed_reload_keeps_the_rule_and_says_so(
    client, admin, zone_settings, monkeypatch
):
    from dnsrules.rules import services
    from dnsrules.unbound.control import ControlError

    client.get("/rules/")
    kids = Group.objects.get(name="kids")

    def boom(path, name):
        raise ControlError("connection refused")

    monkeypatch.setattr(services.control, "auth_zone_reload", boom)
    zone_settings.UNBOUND_CONTROL_SOCKET = "/run/unbound/control.sock"

    response = add(client, kids, "ads.example.com")

    assert response.status_code == 200
    assert Rule.objects.count() == 1
    assert "unbound was not updated" in response.content.decode()
