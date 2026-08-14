import os
import re
import subprocess
import sys

import pytest
from django.core.management import call_command


def test_settings_import_with_an_empty_environment():
    """The install procedure runs commands before the environment file exists."""
    env = {key: value for key, value in os.environ.items() if key == "PATH"}
    subprocess.run(
        [sys.executable, "-c", "import dnsrules.settings"],
        check=True,
        env=env,
    )


def test_system_checks_pass():
    call_command("check")


def test_dashboard_requires_a_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert response.headers["Location"].startswith("/login/")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path,label",
    [("/", "Dashboard"), ("/queries/", "Queries"), ("/rules/", "Rules")],
)
def test_the_nav_marks_the_page_you_are_on_and_no_other(
    client, django_user_model, path, label
):
    user = django_user_model.objects.create_user(username="tim", password="secret")
    client.force_login(user)

    body = client.get(path).content.decode()

    marked = re.findall(r'<a[^>]*aria-current="page"[^>]*>([^<]+)</a>', body)
    assert marked == [label]


def test_vendored_htmx_is_served(client):
    """WhiteNoise reads the finders, so no collectstatic step exists to fail."""
    response = client.get("/static/dnsrules/htmx.min.js")
    assert response.status_code == 200


def test_login_page_sends_the_csrf_token_the_htmx_4_way(client):
    """htmx 4 inheritance is explicit. Without :inherited every POST fails."""
    body = client.get("/login/").content.decode()
    assert "hx-headers:inherited=" in body
    assert "X-CSRFToken" in body
