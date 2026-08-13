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
