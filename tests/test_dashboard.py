from datetime import timedelta

import pytest
from django.utils import timezone

from dnsrules.queries import stats
from dnsrules.queries.models import BlockedBy, Client, Query

pytestmark = pytest.mark.django_db

HTMX = {"HTTP_HX_REQUEST": "true"}
DAY = timedelta(days=1)


@pytest.fixture
def admin(client, django_user_model):
    user = django_user_model.objects.create_user(username="tim", password="secret")
    client.force_login(user)
    return user


def log(qname, count, *, address="10.0.0.2", blocked="", ago=timedelta()):
    Query.objects.bulk_create(
        Query(
            at=timezone.now() - ago,
            client=address,
            qname=qname,
            qtype="A",
            rcode="NXDOMAIN" if blocked else "NOERROR",
            blocked_by=blocked,
        )
        for _ in range(count)
    )


@pytest.fixture
def counted(db):
    """Eleven queries in the last day, and five from three days back."""
    log("ads.example.com", 6, blocked=BlockedBy.FEED)
    log("news.example.com", 2)
    log("cdn.example.com", 3, address="10.0.1.50")
    log("old.example.com", 5, ago=timedelta(days=3))


@pytest.fixture
def since():
    return timezone.now() - DAY


def test_the_blocked_chart_holds_only_blocked_names(counted, since):
    bars = stats.top(since, blocked=True)
    assert [(bar.label, bar.count) for bar in bars] == [("ads.example.com", 6)]
    # The whole bar is the blocked part, so the chart draws it in one colour.
    assert bars[0].blocked == bars[0].count


def test_the_allowed_chart_holds_the_rest_most_asked_first(counted, since):
    bars = stats.top(since, blocked=False)
    assert [(bar.label, bar.count) for bar in bars] == [
        ("cdn.example.com", 3),
        ("news.example.com", 2),
    ]


def test_a_client_bar_carries_the_part_of_its_traffic_that_was_stopped(counted, since):
    busiest, quieter = stats.clients(since)

    assert (busiest.label, busiest.count, busiest.blocked) == ("10.0.0.2", 8, 6)
    assert busiest.blocked_share == pytest.approx(75)
    assert (quieter.label, quieter.count, quieter.blocked) == ("10.0.1.50", 3, 0)


def test_the_shares_scale_to_the_largest_bar(counted, since):
    busiest, quieter = stats.clients(since)
    assert busiest.share == pytest.approx(100)
    assert quieter.share == pytest.approx(37.5)


def test_a_named_client_shows_its_name(counted, since):
    Client.objects.create(address="10.0.0.2", name="clove")
    assert stats.clients(since)[0].label == "clove"


def test_the_timeline_has_a_bucket_for_each_quiet_hour(counted, since):
    """A chart that skipped them would draw a silent hour as if it never was."""
    data = stats.timeline(since, "hour")

    assert len(data["labels"]) == 25
    assert data["allowed"][-1] == 5
    assert data["blocked"][-1] == 6
    assert data["allowed"].count(0) == 24


def test_the_two_series_stack_rather_than_overlap(counted, since):
    """Chart.js adds them, so a blocked query must be in one series only."""
    data = stats.timeline(since, "hour")
    assert sum(data["allowed"]) == 5
    assert sum(data["blocked"]) == 6


def test_the_timeline_holds_every_row_in_the_window(counted):
    week = stats.timeline(timezone.now() - timedelta(days=7), "hour")
    assert sum(week["allowed"]) + sum(week["blocked"]) == 16


def test_a_tooltip_names_the_day_and_a_tick_names_the_time(counted, since):
    data = stats.timeline(since, "hour")
    assert data["labels"][-1].count(":") == 1
    assert data["stamps"][-1].endswith(data["labels"][-1])
    assert len(data["stamps"][-1]) > len(data["labels"][-1])


def test_the_dashboard_counts_the_default_window(client, admin, counted):
    body = client.get("/").content.decode()

    assert "11 queries" in body
    assert "ads.example.com" in body
    # Three days old, and the default window is one day.
    assert "old.example.com" not in body


def test_a_longer_window_reaches_further_back(client, admin, counted):
    body = client.get("/", {"window": "7d"}, **HTMX).content.decode()
    assert "old.example.com" in body


def test_a_bar_links_into_the_log_for_the_same_window(client, admin, counted):
    body = client.get("/").content.decode()
    assert "/queries/?qname=ads.example.com&amp;window=24h" in body
    assert "/queries/?client=10.0.0.2&amp;window=24h" in body


def test_an_unknown_window_falls_back_to_the_default(client, admin, counted):
    body = client.get("/", {"window": "all of it"}).content.decode()
    assert '<option value="24h" selected>' in body


def test_an_htmx_request_answers_with_the_panel_alone(client, admin, counted):
    body = client.get("/", **HTMX).content.decode()
    assert 'id="summary"' in body
    assert "<html" not in body


def test_the_swapped_panel_carries_the_canvas_and_its_data(client, admin, counted):
    """The chart is inside the swap, so a swap has to bring both."""
    body = client.get("/", {"window": "1h"}, **HTMX).content.decode()

    assert 'id="timeline"' in body
    payload = body[body.index('id="timeline-data"') :]
    assert '"blocked": [' in payload
    assert '"stamps": [' in payload


def test_the_chart_library_is_pinned_to_its_hash(client, admin, counted):
    """It comes from a CDN, so the page states what it will accept."""
    body = client.get("/").content.decode()
    assert "cdnjs.cloudflare.com" in body
    assert 'integrity="sha512-' in body
    assert 'crossorigin="anonymous"' in body
    # The UMD build. chart.min.js is an ES module, and a script tag stops on
    # its first import statement.
    assert "chart.umd.min.js" in body


def test_the_chart_script_is_served(client):
    assert client.get("/static/dnsrules/charts.js").status_code == 200
