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


class Client(models.Model):
    """A name for an address, set by hand from the query log.

    Ansible used to render these. It no longer does: the website is the control
    plane, so the name belongs where a person can change it without a deploy.
    An address with no row shows as itself.
    """

    address = models.GenericIPAddressField(unique=True)
    name = models.CharField(max_length=64)

    objects = models.Manager()

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.address})"


class Query(models.Model):
    at = models.DateTimeField()
    client = models.GenericIPAddressField()
    qname = models.CharField(max_length=MAX_LENGTH)
    qtype = models.CharField(max_length=16)
    # Empty when no answer arrived inside the pairing window. No rcode is
    # spelled that way, so one empty value is enough.
    rcode = models.CharField(max_length=16, blank=True)
    reply_ms = models.FloatField(null=True, blank=True)
    # A policy NXDOMAIN clears the RA bit, where `rpz-signal-nxdomain-ra: yes`
    # is set on the zone. That is the whole signal, and it is read from the
    # answer itself. It cannot name the zone that acted.
    blocked = models.BooleanField(default=False)

    objects = models.Manager()

    class Meta:
        ordering = ["-at"]
        verbose_name_plural = "queries"
        indexes = [
            BrinIndex(fields=["at"], name="queries_query_at_brin"),
            # The log table filters on these two.
            models.Index(fields=["qname"], name="queries_query_qname"),
            models.Index(fields=["client"], name="queries_query_client"),
        ]

    def __str__(self) -> str:
        return f"{self.qname} {self.qtype}"
