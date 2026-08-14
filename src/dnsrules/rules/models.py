"""Rules live here. The zone is rendered output.

Two browser tabs and the web workers all change rules. A file makes that a
read-modify-write race that needs its own locking. A transaction solves it
already, and the rules page can then join against the query log to show how
often each rule fires.

See `dnsrules.rules.services` for what unbound fetches.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from dnsrules.unbound.domain import MAX_LENGTH, InvalidDomain, normalize
from dnsrules.unbound.zone import Action

NAME_MAX_LENGTH = 64

ACTION_CHOICES = [
    (Action.BLOCK.value, "Block, answer NXDOMAIN"),
    (Action.BLOCK_NODATA.value, "Block, answer NODATA"),
    (Action.ALLOW.value, "Allow, skip the blocklist"),
]


class Source(models.TextChoices):
    MANUAL = "manual", "Added by hand"
    QUERY_LOG = "query_log", "Added from the query log"


class Group(models.Model):
    """A set of rules with its own RPZ zone, which unbound fetches.

    `name` picks the URL, at `/rpz/<name>.zone`. `zone` is what unbound calls
    that zone, and it is the argument to `auth_zone_transfer`. One group is
    enough until a rule has to reach one client and not another.
    """

    name = models.CharField(max_length=NAME_MAX_LENGTH, unique=True)
    # The RPZ zone name inside unbound.conf. Ansible owns that file, so this
    # has to match what it writes.
    zone = models.CharField(max_length=NAME_MAX_LENGTH)
    # unbound accepts a transfer only when the serial rises, so it has to
    # outlive a restart of either side.
    serial = models.BigIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    objects = models.Manager()

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class RuleQuerySet(models.QuerySet):
    def active(self, now: timezone.datetime | None = None) -> RuleQuerySet:
        now = now or timezone.now()
        return self.filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))

    def expired(self, now: timezone.datetime | None = None) -> RuleQuerySet:
        now = now or timezone.now()
        return self.filter(expires_at__isnull=False, expires_at__lte=now)


class Rule(models.Model):
    group = models.ForeignKey(Group, on_delete=models.CASCADE, related_name="rules")
    domain = models.CharField(max_length=MAX_LENGTH)
    action = models.CharField(
        max_length=16, choices=ACTION_CHOICES, default=Action.BLOCK.value
    )
    source = models.CharField(
        max_length=16, choices=Source.choices, default=Source.MANUAL
    )
    # Null means permanent. Expiry belongs here because the zone format has
    # nowhere to record it.
    expires_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RuleQuerySet.as_manager()

    class Meta:
        ordering = ["group__name", "domain"]
        indexes = [models.Index(fields=["expires_at"])]
        constraints = [
            # Each group has its own zone, so one domain holds one rule per
            # group and no more.
            models.UniqueConstraint(
                fields=["group", "domain"], name="one_rule_per_domain_per_group"
            )
        ]

    def __str__(self) -> str:
        return f"{self.domain} {self.action}"

    def save(self, *args, **kwargs) -> None:
        # Normalize here as well as in clean(), so that no path into the table
        # can store a domain that render() would later refuse. A rule that
        # cannot render blocks every other rule from reaching unbound.
        self.domain = normalize(self.domain)
        super().save(*args, **kwargs)

    def clean(self) -> None:
        try:
            self.domain = normalize(self.domain)
        except InvalidDomain as error:
            raise ValidationError({"domain": str(error)}) from error

    @property
    def is_expired(self) -> bool:
        return self.expires_at is not None and self.expires_at <= timezone.now()
