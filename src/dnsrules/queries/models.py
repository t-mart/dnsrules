"""The query log: one row for each question a client asked.

The table is partitioned by day. Migration 0001 writes the DDL by hand, because
Django models no part of declarative partitioning. Two consequences worth
knowing:

- The primary key is `(at, id)`. Postgres demands the partition key inside
  every unique constraint. Django still treats `id` as the primary key, which
  works, because nothing here updates a row by primary key.
- Retention drops a partition rather than deleting rows. A DROP is instant and
  leaves nothing to vacuum.
"""

from django.db import models

from dnsrules.unbound.domain import MAX_LENGTH


class Query(models.Model):
    at = models.DateTimeField()
    client = models.GenericIPAddressField()
    qname = models.CharField(max_length=MAX_LENGTH)
    qtype = models.CharField(max_length=16)
    # Empty when no answer arrived inside the pairing window. No rcode is
    # spelled that way, so one empty value is enough.
    rcode = models.CharField(max_length=16, blank=True)
    reply_ms = models.FloatField(null=True, blank=True)
    # NXDOMAIN with the RA bit cleared, which `rpz-signal-nxdomain-ra` sets on
    # a policy answer. It names no zone, and nothing here needs one.
    blocked = models.BooleanField(default=False)

    objects = models.Manager()

    class Meta:
        ordering = ["-at"]
        verbose_name_plural = "queries"

    def __str__(self) -> str:
        return f"{self.qname} {self.qtype}"


class Hour(models.Model):
    """One hour of one client's traffic, blocked or not, and how many.

    It carries no name, and that is the whole point. Measured on a real
    capture, an hourly rollup keyed on the name holds near 1,600 rows an hour,
    which is 15 million rows over 13 months. The raw table it replaces holds
    7.5 million. An archive that costs twice the thing it archives is not one.

    Without the name it holds one row for each client and each outcome, near
    600 a day. `Top` keeps the names that are worth keeping.
    """

    # The hour it covers, at its start.
    at = models.DateTimeField()
    client = models.GenericIPAddressField()
    blocked = models.BooleanField()
    count = models.PositiveIntegerField()

    objects = models.Manager()

    class Meta:
        ordering = ["-at"]
        constraints = [
            # The rollup upserts on this, and it indexes `at` for retention.
            models.UniqueConstraint(
                fields=["at", "client", "blocked"],
                name="one_row_per_client_per_hour",
            )
        ]

    def __str__(self) -> str:
        return f"{self.client} {self.at:%Y-%m-%d %H}h"


class Top(models.Model):
    """The names asked for most on one day, blocked and allowed apart.

    The tail is what makes an archive expensive, and it is also the part
    nobody reads. In one capture, 608 queries held 162 names, and the top 50
    covered 64 percent of them. So this keeps a head and drops the tail.

    The last 30 days need none of this. Raw rows answer any question about
    them, down to the client and the second.
    """

    # The local day it covers. TIME_ZONE decides where a day starts.
    at = models.DateField()
    qname = models.CharField(max_length=MAX_LENGTH)
    blocked = models.BooleanField()
    count = models.PositiveIntegerField()

    objects = models.Manager()

    class Meta:
        ordering = ["-at", "-count"]
        constraints = [
            models.UniqueConstraint(
                fields=["at", "qname", "blocked"], name="one_row_per_name_per_day"
            )
        ]

    def __str__(self) -> str:
        return f"{self.qname} {self.at}"
