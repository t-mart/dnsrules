"""The scheduler.

The lock is the point. Everything else here is a table with a timestamp in it.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from dnsrules.core import jobs
from dnsrules.core.models import Job

pytestmark = pytest.mark.django_db


@pytest.fixture
def schedule(monkeypatch):
    """A schedule of one job that records its calls."""
    calls = []
    monkeypatch.setattr(
        jobs,
        "SCHEDULE",
        {"counter": (timedelta(minutes=5), "test_jobs.count")},
    )
    monkeypatch.setattr("test_jobs.CALLS", calls)
    return calls


CALLS: list = []


def count() -> None:
    CALLS.append(timezone.now())


def test_sync_gives_every_job_a_row(schedule):
    jobs.sync()
    assert [job.name for job in Job.objects.all()] == ["counter"]


def test_sync_drops_a_job_nothing_runs(schedule):
    Job.objects.create(name="removed", run_at=timezone.now())
    jobs.sync()
    assert [job.name for job in Job.objects.all()] == ["counter"]


def test_sync_keeps_the_schedule_of_a_row_it_already_made(schedule):
    jobs.sync()
    later = timezone.now() + timedelta(hours=3)
    Job.objects.filter(name="counter").update(run_at=later)
    jobs.sync()
    assert Job.objects.get(name="counter").run_at == later


def test_run_due_runs_a_job_that_is_due(schedule):
    jobs.sync()
    assert jobs.run_due() == "counter"
    assert len(schedule) == 1


def test_run_due_leaves_a_job_that_is_not_due(schedule):
    jobs.sync()
    jobs.run_due()
    assert jobs.run_due() is None
    assert len(schedule) == 1


def test_a_run_sets_the_next_turn_from_the_interval(schedule):
    jobs.sync()
    now = timezone.now()
    jobs.run_due(now)
    job = Job.objects.get(name="counter")
    assert job.run_at == now + timedelta(minutes=5)
    assert job.last_run == now


def test_a_failure_is_recorded_rather_than_raised(schedule, monkeypatch):
    """A worker that dies on one bad job stops every other job."""
    monkeypatch.setattr(
        jobs, "SCHEDULE", {"counter": (timedelta(minutes=5), "test_jobs.boom")}
    )
    jobs.sync()
    assert jobs.run_due() == "counter"
    assert "the resolver is out" in Job.objects.get(name="counter").last_error


def test_a_failure_comes_back_sooner_than_its_interval(schedule, monkeypatch):
    monkeypatch.setattr(
        jobs, "SCHEDULE", {"counter": (timedelta(hours=1), "test_jobs.boom")}
    )
    jobs.sync()
    now = timezone.now()
    jobs.run_due(now)
    assert Job.objects.get(name="counter").run_at == now + jobs.RETRY


def test_a_good_run_clears_the_last_error(schedule):
    jobs.sync()
    Job.objects.filter(name="counter").update(last_error="an old failure")
    jobs.run_due()
    assert Job.objects.get(name="counter").last_error == ""


def test_nudge_makes_a_job_due_now(schedule):
    jobs.sync()
    Job.objects.filter(name="counter").update(
        run_at=timezone.now() + timedelta(hours=3)
    )
    jobs.nudge("counter")
    assert jobs.run_due() == "counter"


def test_run_all_due_takes_every_job_that_is_waiting(monkeypatch):
    monkeypatch.setattr(
        jobs,
        "SCHEDULE",
        {
            "one": (timedelta(minutes=5), "test_jobs.count"),
            "two": (timedelta(minutes=5), "test_jobs.count"),
        },
    )
    jobs.sync()
    assert jobs.run_all_due() == 2


def boom() -> None:
    raise RuntimeError("the resolver is out")


def test_every_scheduled_target_imports():
    """A typo in SCHEDULE would only show at the moment the job came due."""
    from django.utils.module_loading import import_string

    for interval, target in jobs.SCHEDULE.values():
        assert callable(import_string(target))
        assert interval.total_seconds() > 0
