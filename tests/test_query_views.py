from datetime import timedelta

import pytest
from django.utils import timezone

from dnsrules.queries.models import BlockedBy, Client, Query
from dnsrules.rules import services
from dnsrules.rules.models import Group, Rule, Source
from dnsrules.unbound.zone import Action

pytestmark = pytest.mark.django_db

HTMX = {"HTTP_HX_REQUEST": "true"}


@pytest.fixture
def admin(client, django_user_model):
    user = django_user_model.objects.create_user(username="tim", password="secret")
    client.force_login(user)
    return user


@pytest.fixture
def logged(zone_settings):
    now = timezone.now()
    Query.objects.create(
        at=now,
        client="10.0.0.2",
        qname="ads.example.com",
        qtype="A",
        blocked_by=BlockedBy.FEED,
        rcode="NXDOMAIN",
    )
    Query.objects.create(
        at=now,
        client="10.0.1.50",
        qname="news.example.com",
        qtype="AAAA",
        rcode="NOERROR",
        reply_ms=12.5,
    )
    Query.objects.create(
        at=now - timedelta(days=2),
        client="10.0.0.2",
        qname="old.example.com",
        qtype="A",
        rcode="NOERROR",
    )


def test_the_log_needs_a_login(client):
    assert client.get("/queries/").status_code == 302


def test_the_log_lists_rows_in_the_window(client, admin, logged):
    body = client.get("/queries/").content.decode()
    assert "ads.example.com" in body
    assert "news.example.com" in body
    # Two days old, and the default window is one hour.
    assert "old.example.com" not in body


def test_the_window_filter_reaches_further_back(client, admin, logged):
    body = client.get("/queries/", {"window": "7d"}, **HTMX).content.decode()
    assert "old.example.com" in body


def test_each_filter_narrows_the_rows(client, admin, logged):
    def names(**terms):
        body = client.get("/queries/", terms, **HTMX).content.decode()
        return {
            name for name in ("ads.example.com", "news.example.com") if name in body
        }

    assert names(client="10.0.0.2") == {"ads.example.com"}
    assert names(qname="news") == {"news.example.com"}
    assert names(qtype="aaaa") == {"news.example.com"}
    assert names(status="blocked") == {"ads.example.com"}
    assert names(status="allowed") == {"news.example.com"}


def test_an_unnamed_client_shows_its_address(client, admin, logged):
    body = client.get("/queries/").content.decode()
    assert "10.0.0.2" in body


def test_a_named_client_shows_its_name(client, admin, logged):
    Client.objects.create(address="10.0.0.2", name="laptop")
    body = client.get("/queries/").content.decode()
    assert "laptop" in body


def test_naming_a_client_from_a_row(client, admin, logged):
    response = client.post(
        "/queries/client/", {"address": "10.0.0.2", "name": "laptop"}, **HTMX
    )
    assert response.status_code == 200
    assert Client.objects.get(address="10.0.0.2").name == "laptop"
    assert "laptop" in response.content.decode()


def test_an_empty_name_takes_the_name_back(client, admin, logged):
    Client.objects.create(address="10.0.0.2", name="laptop")
    client.post("/queries/client/", {"address": "10.0.0.2", "name": ""}, **HTMX)
    assert Client.objects.count() == 0


def test_naming_something_that_is_not_an_address_is_refused(client, admin, logged):
    response = client.post(
        "/queries/client/", {"address": "not-an-address", "name": "x"}, **HTMX
    )
    assert response.status_code == 422
    assert Client.objects.count() == 0


def test_blocking_from_a_row_writes_a_rule_and_reaches_the_zone(client, admin, logged):

    response = client.post(
        "/queries/rule/",
        {"domain": "ads.example.com", "group": "kids", "action": Action.BLOCK},
        **HTMX,
    )

    assert response.status_code == 200
    rule = Rule.objects.get()
    assert rule.action == Action.BLOCK
    assert rule.source == Source.QUERY_LOG
    assert rule.expires_at is None
    assert "ads.example.com CNAME ." in services.zone_text(
        Group.objects.get(name="kids")
    )


def test_allowing_from_a_row_replaces_the_block(client, admin, logged):
    client.get("/rules/")
    post = {"domain": "ads.example.com", "group": "kids"}
    client.post("/queries/rule/", post | {"action": Action.BLOCK}, **HTMX)
    client.post("/queries/rule/", post | {"action": Action.ALLOW}, **HTMX)

    assert Rule.objects.count() == 1
    assert Rule.objects.get().action == Action.ALLOW
    kids = Group.objects.get(name="kids")
    assert "ads.example.com CNAME rpz-passthru." in services.zone_text(kids)


def test_a_duration_makes_the_rule_temporary(client, admin, logged):
    client.get("/rules/")
    client.post(
        "/queries/rule/",
        {
            "domain": "ads.example.com",
            "group": "kids",
            "action": Action.ALLOW,
            "duration": "3600",
        },
        **HTMX,
    )
    assert Rule.objects.get().expires_at is not None


def test_a_group_that_does_not_exist_is_refused(client, admin, logged):
    response = client.post(
        "/queries/rule/",
        {"domain": "ads.example.com", "group": "nobody", "action": Action.BLOCK},
        **HTMX,
    )
    assert response.status_code == 422
    assert Rule.objects.count() == 0


def test_a_bad_domain_is_refused(client, admin, logged):
    response = client.post(
        "/queries/rule/",
        {"domain": "not a domain", "group": "kids", "action": Action.BLOCK},
        **HTMX,
    )
    assert response.status_code == 422
    assert Rule.objects.count() == 0


def test_an_unknown_action_is_refused(client, admin, logged):
    response = client.post(
        "/queries/rule/",
        {"domain": "ads.example.com", "group": "kids", "action": "delete_everything"},
        **HTMX,
    )
    assert response.status_code == 422
    assert Rule.objects.count() == 0
