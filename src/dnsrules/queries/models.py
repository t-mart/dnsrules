"""The query log: one row for each question a client asked.

One table, and a DELETE past the retention window. The house makes about
250,000 queries a day, so 30 days is near 7.5 million rows. Postgres does not
notice that, and an archive that holds less than the thing it archives is not
worth the code.

The rows arrive in time order, so `at` carries a BRIN index. It costs a
fraction of what a btree would take at this row count.
"""

from django.contrib.postgres.indexes import BrinIndex
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
        indexes = [
            BrinIndex(fields=["at"], name="queries_query_at_brin"),
            # The log table filters on both of these.
            models.Index(fields=["qname"], name="queries_query_qname"),
            models.Index(fields=["client"], name="queries_query_client"),
        ]

    def __str__(self) -> str:
        return f"{self.qname} {self.qtype}"
