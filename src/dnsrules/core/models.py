"""The job table.

One row for each recurring job. The row is the schedule, the lock, and the
record of the last run, so there is no broker and no second process to keep
alive.
"""

from django.db import models


class Job(models.Model):
    name = models.CharField(max_length=64, unique=True)
    # When this job is next due. Setting it to now is how the website asks for
    # a job to run at once.
    run_at = models.DateTimeField()
    last_run = models.DateTimeField(null=True, blank=True)
    # Empty after a run that worked. The rules page reads it.
    last_error = models.TextField(blank=True)

    objects = models.Manager()

    class Meta:
        ordering = ["name"]
        indexes = [models.Index(fields=["run_at"])]

    def __str__(self) -> str:
        return self.name
