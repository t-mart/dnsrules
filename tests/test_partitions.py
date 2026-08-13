from datetime import UTC, date, datetime, timedelta

import pytest
from django.db import connection

from dnsrules.queries import partitions
from dnsrules.queries.models import Query

pytestmark = pytest.mark.django_db

TODAY = date(2026, 8, 13)


def partition_of(at: datetime) -> str:
    """The partition a row actually landed in."""
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT tableoid::regclass::text FROM {partitions.TABLE} WHERE at = %s",
            [at],
        )
        return cursor.fetchone()[0]


def make(at: datetime) -> datetime:
    Query.objects.create(
        at=at, client="10.0.0.2", qname="example.com", qtype="A", rcode="NOERROR"
    )
    return at


def test_the_table_is_partitioned():
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT relkind FROM pg_class WHERE relname = %s", [partitions.TABLE]
        )
        assert cursor.fetchone()[0] == "p"


def test_reconcile_creates_today_and_the_days_ahead():
    added, _ = partitions.reconcile(TODAY, ahead=3, keep=30)
    assert added == [TODAY + timedelta(days=offset) for offset in range(4)]


def test_reconcile_runs_twice_without_complaint():
    partitions.reconcile(TODAY, ahead=2, keep=30)
    added, dropped = partitions.reconcile(TODAY, ahead=2, keep=30)
    assert added == []
    assert dropped == []


def test_reconcile_drops_the_days_past_retention():
    old = TODAY - timedelta(days=40)
    partitions.create(old)
    _, dropped = partitions.reconcile(TODAY, ahead=1, keep=30)
    assert dropped == [old]
    assert partitions.name_for(old) not in partitions.existing()


def test_a_row_lands_in_the_partition_for_its_day():
    partitions.reconcile(TODAY, ahead=1, keep=30)
    at = make(datetime(2026, 8, 13, 12, 30, tzinfo=UTC))
    assert partition_of(at) == partitions.name_for(TODAY)


def test_a_row_with_no_partition_lands_in_the_default_one():
    """Nothing is lost when a day has no partition. That is the whole point."""
    at = make(datetime(2031, 1, 1, tzinfo=UTC))
    assert partition_of(at) == partitions.DEFAULT_PARTITION
    assert partitions.default_rows() == 1


def test_dropping_a_day_removes_its_rows():
    partitions.reconcile(TODAY, ahead=0, keep=30)
    make(datetime(2026, 8, 13, 12, 30, tzinfo=UTC))
    assert Query.objects.count() == 1
    partitions.drop(TODAY)
    assert Query.objects.count() == 0


def test_dropping_a_day_that_is_absent_reports_it():
    assert partitions.drop(date(2020, 1, 1)) is False


def test_size_counts_the_partitions_and_not_the_parent():
    """The parent holds no rows, so measuring it alone always reads zero."""
    partitions.reconcile(TODAY, ahead=0, keep=30)
    assert partitions.size() > 0


def test_the_cap_drops_the_oldest_day_first():
    for offset in (3, 2, 1):
        partitions.create(TODAY - timedelta(days=offset))
    dropped = partitions.enforce_cap(0, TODAY)
    assert dropped == [TODAY - timedelta(days=offset) for offset in (3, 2, 1)]


def test_the_cap_leaves_today_and_the_days_ahead():
    """A full disk still has to leave a log that accepts rows."""
    partitions.reconcile(TODAY, ahead=2, keep=30)
    partitions.enforce_cap(0, TODAY)
    assert set(partitions.existing().values()) == {
        TODAY + timedelta(days=offset) for offset in range(3)
    }


def test_the_cap_does_nothing_under_the_limit():
    partitions.reconcile(TODAY, ahead=1, keep=30)
    assert partitions.enforce_cap(10 * 1024**3, TODAY) == []
