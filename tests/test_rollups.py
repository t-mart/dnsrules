from datetime import UTC, date, datetime, timedelta

import pytest

from dnsrules.queries import partitions, rollups
from dnsrules.queries.models import Hour, Query, Top

pytestmark = pytest.mark.django_db

TODAY = date(2026, 8, 13)
NOW = datetime(2026, 8, 13, 12, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def days():
    """Rows need a partition for their day, as they do on the router."""
    partitions.reconcile(TODAY - timedelta(days=5), ahead=10, keep=30)


def make(at: datetime, *, client="10.0.0.2", qname="example.com", blocked=False):
    Query.objects.create(
        at=at,
        client=client,
        qname=qname,
        qtype="A",
        rcode="NXDOMAIN" if blocked else "NOERROR",
        blocked=blocked,
    )


def test_an_hour_counts_each_client_and_each_outcome():
    for minute in range(3):
        make(datetime(2026, 8, 13, 9, minute, tzinfo=UTC))
    make(datetime(2026, 8, 13, 9, 5, tzinfo=UTC), blocked=True)
    make(datetime(2026, 8, 13, 9, 6, tzinfo=UTC), client="10.0.0.3")

    rollups.roll_hours(NOW)

    assert Hour.objects.count() == 3
    row = Hour.objects.get(client="10.0.0.2", blocked=False)
    assert row.count == 3
    assert row.at == datetime(2026, 8, 13, 9, tzinfo=UTC)


def test_the_hour_that_is_still_filling_waits():
    """A count that changes after it is written is worse than one that is late."""
    make(datetime(2026, 8, 13, 12, 15, tzinfo=UTC))
    make(datetime(2026, 8, 13, 11, 15, tzinfo=UTC))
    rollups.roll_hours(NOW)
    assert [row.at.hour for row in Hour.objects.all()] == [11]


def test_a_second_run_writes_the_same_numbers():
    make(datetime(2026, 8, 13, 9, 0, tzinfo=UTC))
    rollups.roll_hours(NOW)
    make(datetime(2026, 8, 13, 9, 30, tzinfo=UTC))
    rollups.roll_hours(NOW)
    assert Hour.objects.count() == 1
    assert Hour.objects.get().count == 1


def test_a_later_run_carries_on_from_the_archive():
    make(datetime(2026, 8, 13, 9, 0, tzinfo=UTC))
    rollups.roll_hours(NOW)
    make(datetime(2026, 8, 13, 10, 0, tzinfo=UTC))
    assert rollups.roll_hours(NOW) == 1
    assert Hour.objects.count() == 2


def test_nothing_to_roll_writes_nothing():
    assert rollups.roll_hours(NOW) == 0


def test_a_day_keeps_the_leading_names_and_drops_the_tail():
    yesterday = datetime(2026, 8, 12, 9, tzinfo=UTC)
    for index in range(5):
        for _ in range(5 - index):
            make(yesterday, qname=f"name{index}.example.com")

    rollups.roll_days(NOW, top=3)

    kept = list(Top.objects.filter(blocked=False).values_list("qname", "count"))
    assert kept == [
        ("name0.example.com", 5),
        ("name1.example.com", 4),
        ("name2.example.com", 3),
    ]


def test_blocked_names_rank_apart():
    """A blocked name is rare, so a shared list would never show one."""
    yesterday = datetime(2026, 8, 12, 9, tzinfo=UTC)
    for _ in range(20):
        make(yesterday, qname="busy.example.com")
    make(yesterday, qname="ads.example.com", blocked=True)

    rollups.roll_days(NOW, top=1)

    assert Top.objects.get(blocked=True).qname == "ads.example.com"
    assert Top.objects.get(blocked=False).qname == "busy.example.com"


def test_the_day_that_is_still_filling_waits():
    make(datetime(2026, 8, 13, 9, tzinfo=UTC))
    assert rollups.roll_days(NOW) == 0


def test_a_day_is_stamped_with_the_day_it_covers():
    make(datetime(2026, 8, 12, 9, tzinfo=UTC))
    rollups.roll_days(NOW)
    assert Top.objects.get().at == date(2026, 8, 12)


def test_prune_drops_rows_past_retention():
    Hour.objects.create(
        at=datetime(2025, 1, 5, tzinfo=UTC), client="10.0.0.2", blocked=False, count=1
    )
    Top.objects.create(
        at=date(2025, 1, 5), qname="old.example.com", blocked=False, count=1
    )
    Hour.objects.create(
        at=datetime(2026, 8, 1, tzinfo=UTC), client="10.0.0.2", blocked=False, count=1
    )

    assert rollups.prune(TODAY, months=13) == 2
    assert Hour.objects.count() == 1
    assert Top.objects.count() == 0


def test_retention_cuts_at_a_whole_month():
    """Thirteen months back from any day is the first of that month."""
    assert rollups._months_ago(date(2026, 8, 13), 13) == date(2025, 7, 1)
    assert rollups._months_ago(date(2026, 1, 31), 13) == date(2024, 12, 1)


def test_reconcile_rolls_both_and_reports_all_three():
    make(datetime(2026, 8, 12, 9, tzinfo=UTC))
    make(datetime(2026, 8, 13, 9, tzinfo=UTC))
    hours, days, dropped = rollups.reconcile(NOW)
    assert (hours, days, dropped) == (2, 1, 0)
