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


class BlockedBy(models.TextChoices):
    """What stopped the answer. Empty means nothing did.

    Measured against unbound 1.26.0, an answer carries one usable signal: a
    policy NXDOMAIN clears the RA bit, where `rpz-signal-nxdomain-ra: yes` is
    set on the zone. Nothing else separates a block from an ordinary answer.
    The AA bit does not: unbound sets it for every local zone, including the
    LAN names and `.invalid`.

    That signal cannot name the zone, and it misses a `CNAME *.` rule outright,
    because NODATA reads exactly like a legitimate empty answer. So a rule is
    read from the rules table, which is exact, and the signal covers the feed.
    """

    RULE = "rule", "A dnsrules rule"
    FEED = "feed", "The blocklist"


class Query(models.Model):
    at = models.DateTimeField()
    client = models.GenericIPAddressField()
    qname = models.CharField(max_length=MAX_LENGTH)
    qtype = models.CharField(max_length=16)
    # Empty when no answer arrived inside the pairing window. No rcode is
    # spelled that way, so one empty value is enough.
    rcode = models.CharField(max_length=16, blank=True)
    reply_ms = models.FloatField(null=True, blank=True)
    blocked_by = models.CharField(max_length=8, choices=BlockedBy, blank=True)

    objects = models.Manager()

    class Meta:
        ordering = ["-at"]
        verbose_name_plural = "queries"
        indexes = [
            BrinIndex(fields=["at"], name="queries_query_at_brin"),
            # The log table filters on these three.
            models.Index(fields=["qname"], name="queries_query_qname"),
            models.Index(fields=["client"], name="queries_query_client"),
            models.Index(fields=["blocked_by"], name="queries_query_blocked_by"),
        ]

    def __str__(self) -> str:
        return f"{self.qname} {self.qtype}"

    @property
    def blocked(self) -> bool:
        return bool(self.blocked_by)
