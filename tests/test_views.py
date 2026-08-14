from datetime import timedelta

import pytest
from conftest import rules_in
from django.utils import timezone

from dnsrules.core import jobs
from dnsrules.core.models import Job
from dnsrules.rules import services
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


def test_adding_a_rule_reaches_the_zone(client, admin, zone_settings):
    kids = Group.objects.get(name="kids")

    response = add(client, kids, "ads.example.com")

    assert response.status_code == 200
    assert rules_in(services.zone_text(kids)) == ["ads.example.com CNAME ."]


def test_a_duration_sets_the_expiry(client, admin, zone_settings):
    kids = Group.objects.get(name="kids")
    add(client, kids, "ads.example.com", duration="3600")
    assert Rule.objects.get().expires_at is not None


def test_a_bad_domain_answers_422_and_changes_nothing(client, admin, zone_settings):
    """htmx 4 swaps a 4xx, so the form redisplays with its errors."""
    kids = Group.objects.get(name="kids")

    response = add(client, kids, "not a domain")

    assert response.status_code == 422
    assert "is not a domain name" in response.content.decode()
    assert rules_in(services.zone_text(kids)) == []


def test_a_repeated_domain_in_one_group_answers_422(client, admin, zone_settings):
    kids = Group.objects.get(name="kids")
    add(client, kids, "ads.example.com")
    assert add(client, kids, "ads.example.com").status_code == 422
    assert Rule.objects.count() == 1


def test_removing_a_rule_leaves_the_zone(client, admin, zone_settings):
    kids = Group.objects.get(name="kids")
    add(client, kids, "ads.example.com")

    response = client.delete(f"/rules/{Rule.objects.get().pk}/", **HTMX)

    assert response.status_code == 200
    assert Rule.objects.count() == 0
    assert rules_in(services.zone_text(kids)) == []


def test_editing_a_rule_changes_the_action(client, admin, zone_settings):
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

    assert rules_in(services.zone_text(kids)) == ["ads.example.com CNAME rpz-passthru."]
    assert Rule.objects.get().note == "school project"


def test_editing_keeps_the_expiry_when_asked(client, admin, zone_settings):
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


def test_saving_a_rule_asks_the_worker_to_tell_unbound(client, admin, zone_settings):
    """The page never reaches unbound. It sets the job due and moves on."""
    jobs.sync()
    Job.objects.filter(name="transfer").update(
        run_at=timezone.now() + timedelta(hours=3)
    )

    add(client, Group.objects.get(name="kids"), "ads.example.com")

    assert Job.objects.get(name="transfer").run_at <= timezone.now()


def test_a_failed_transfer_keeps_the_rule_and_says_so(client, admin, zone_settings):
    jobs.sync()
    Job.objects.filter(name="transfer").update(
        last_error="ControlError: connection refused"
    )

    response = add(client, Group.objects.get(name="kids"), "ads.example.com")

    assert response.status_code == 200
    assert Rule.objects.count() == 1
    assert "connection refused" in response.content.decode()
