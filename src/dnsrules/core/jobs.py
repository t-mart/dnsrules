"""Run the recurring jobs.

The schedule is a table. A worker claims the next due row with `FOR UPDATE SKIP
LOCKED` and pushes it forward before it runs, so a second worker takes the next
job rather than the same one. Nothing else is needed: no broker, no queue, and
no second process.

The claim and the result are each one short transaction. **The job itself runs
between them, in neither.** A job that drives another process needs its writes
visible to that process: `reconcile` raises a serial and then asks unbound to
fetch it, and unbound reads that serial over HTTP on another connection. An
uncommitted serial is one unbound cannot see, so a job held inside a
transaction could never succeed.

Each target is named as a string rather than imported. The jobs live in the
other apps, and those apps import this one.
"""

import logging
import threading
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.utils.module_loading import import_string

from dnsrules.core.models import Job

logger = logging.getLogger(__name__)

# A job that fails comes back soon rather than at its next turn, so a resolver
# that was down for a minute does not leave an error on the page for an hour.
RETRY = timedelta(seconds=30)

TICK = 1.0

SCHEDULE: dict[str, tuple[timedelta, str]] = {
    # Nothing depends on this interval for correctness. A rule change nudges
    # the job, and unbound refetches on the zone SOA whatever happens here.
    "transfer": (timedelta(hours=1), "dnsrules.rules.services.reconcile"),
    # A temporary rule ends within a minute of its expiry.
    "prune": (timedelta(minutes=1), "dnsrules.rules.services.prune"),
    "retention": (timedelta(days=1), "dnsrules.queries.services.retention"),
}


def sync() -> None:
    """Give every job in SCHEDULE a row, and drop the rows nothing runs."""
    Job.objects.bulk_create(
        [Job(name=name, run_at=timezone.now()) for name in SCHEDULE],
        ignore_conflicts=True,
    )
    Job.objects.exclude(name__in=list(SCHEDULE)).delete()


def nudge(name: str) -> None:
    """Ask for a job to run at the next tick.

    The website calls this instead of doing the work. One process talks to
    unbound, and a slow or failing resolver never holds up a page.
    """
    Job.objects.filter(name=name).update(run_at=timezone.now())


def run_due(now: timezone.datetime | None = None) -> str | None:
    """Run one due job. Returns its name, or None when none is due.

    A job that raises is recorded rather than reraised, because a worker that
    dies on one bad job stops every other.
    """
    now = now or timezone.now()
    with transaction.atomic():
        job = (
            Job.objects.select_for_update(skip_locked=True)
            .filter(run_at__lte=now)
            .order_by("run_at")
            .first()
        )
        if job is None:
            return None
        interval, target = SCHEDULE[job.name]
        claimed_run_at = now + interval
        # Take the job off the queue before running it, so the lock covers the
        # claim alone. A worker that dies mid job costs one interval, where a
        # lock held across the work would leave the row claimed until the
        # connection dropped.
        Job.objects.filter(pk=job.pk).update(run_at=claimed_run_at)

    error = ""
    try:
        import_string(target)()
    except Exception as problem:
        logger.exception("The job %s failed.", job.name)
        error = f"{type(problem).__name__}: {problem}"
    with transaction.atomic():
        Job.objects.filter(pk=job.pk).update(last_error=error, last_run=now)
        if error:
            Job.objects.filter(pk=job.pk, run_at=claimed_run_at).update(
                run_at=now + RETRY
            )
    return job.name


def run_all_due() -> int:
    """Run every job that is due now. Returns how many ran."""
    count = 0
    while run_due():
        count += 1
    return count


def worker(stop: threading.Event, tick: float = TICK) -> None:
    """Run due jobs until `stop` is set. This is the whole scheduler."""
    sync()
    while not stop.is_set():
        try:
            run_all_due()
        except Exception:
            # Reaching here means the job table itself is out of reach. Keep
            # ticking: the database comes back, and the jobs are still due.
            logger.exception("The job worker could not read its table.")
        stop.wait(tick)
