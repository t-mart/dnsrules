"""The panel depends on three htmx 4 behaviours that a Python test cannot run.

Assert the markup instead, so an edit that breaks the contract fails here
rather than in the browser.
"""

import pytest

from dnsrules.rules.models import Group, Rule

pytestmark = pytest.mark.django_db


@pytest.fixture
def rule(client, django_user_model, zone_settings):
    user = django_user_model.objects.create_user(username="tim", password="secret")
    client.force_login(user)
    client.get("/rules/")
    return Rule.objects.create(
        group=Group.objects.get(name="kids"), domain="ads.example.com"
    )


@pytest.fixture
def body(client, rule):
    return client.get("/rules/").content.decode()


def test_target_and_swap_are_inherited(body):
    """Inheritance is explicit in htmx 4, and it reaches descendants only."""
    assert 'hx-target:inherited="#rules"' in body
    assert 'hx-swap:inherited="outerHTML"' in body


def test_the_default_swap_is_never_relied_on(body):
    """htmx 4 defaults to innerHTML, which would nest the panel inside itself."""
    assert "hx-swap=" not in body


def test_every_control_points_at_a_route(body, rule):
    assert 'hx-post="/rules/"' in body
    assert f'hx-get="/rules/{rule.pk}/"' in body
    assert f'hx-delete="/rules/{rule.pk}/"' in body
