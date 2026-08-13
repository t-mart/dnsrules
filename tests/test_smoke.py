import os
import subprocess
import sys

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


def test_vendored_htmx_is_served(client):
    """WhiteNoise reads the finders, so no collectstatic step exists to fail."""
    response = client.get("/static/dnsrules/htmx.min.js")
    assert response.status_code == 200


def test_login_page_sends_the_csrf_token_the_htmx_4_way(client):
    """htmx 4 inheritance is explicit. Without :inherited every POST fails."""
    body = client.get("/login/").content.decode()
    assert "hx-headers:inherited=" in body
    assert "X-CSRFToken" in body
