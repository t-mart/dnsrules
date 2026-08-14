"""The query log screen, and the dashboard that counts the same rows.

One table, a filter on each column, and a control on each row. The control is
the point of the project: a name you need is blocked, and you unblock it here
without touching a config file.
"""

import ipaddress
import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from dnsrules.core import jobs
from dnsrules.queries import stats
from dnsrules.queries.models import Client, Query
from dnsrules.rules.forms import DURATIONS
from dnsrules.rules.models import Group, Rule, Source
from dnsrules.rules.views import Request
from dnsrules.unbound.domain import InvalidDomain, normalize
from dnsrules.unbound.zone import Action

logger = logging.getLogger(__name__)

PAGE_SIZE = 50

# Each bounded window, with the bucket the dashboard draws it in. "Everything"
# is not one: it has no bound, and four aggregates over thirty days of rows is
# not a dashboard.
PERIODS = {
    "15m": (timedelta(minutes=15), "minute"),
    "1h": (timedelta(hours=1), "minute"),
    "24h": (timedelta(days=1), "hour"),
    "7d": (timedelta(days=7), "hour"),
}
DEFAULT_PERIOD = "24h"

WINDOW_CHOICES = [
    ("15m", "Last 15 minutes"),
    ("1h", "Last hour"),
    ("24h", "Last day"),
    ("7d", "Last week"),
    ("", "Everything"),
]
PERIOD_CHOICES = [(key, label) for key, label in WINDOW_CHOICES if key in PERIODS]
_SPANS = {key: span for key, (span, _) in PERIODS.items()}

STATUS_CHOICES = [
    ("", "Any status"),
    ("blocked", "Blocked"),
    ("allowed", "Allowed"),
    ("noanswer", "No answer"),
]

# Write the rule to every configured zone. It is the default on the log,
# because a name you want stopped is usually a name you want stopped
# everywhere, and the alternative costs a choice on every row.
EVERY_ZONE = "*"


def _filtered(request: Request):
    """Apply each filter that carries a value. Returns the rows and the terms."""
    terms = {
        "client": request.GET.get("client", "").strip(),
        "qname": request.GET.get("qname", "").strip().lower(),
        "qtype": request.GET.get("qtype", "").strip().upper(),
        "status": request.GET.get("status", "").strip(),
        "window": request.GET.get("window", "1h").strip(),
    }
    rows = Query.objects.all()
    span = _SPANS.get(terms["window"])
    if span is not None:
        rows = rows.filter(at__gte=timezone.now() - span)
    if terms["client"]:
        rows = rows.filter(client=terms["client"])
    if terms["qname"]:
        rows = rows.filter(qname__contains=terms["qname"])
    if terms["qtype"]:
        rows = rows.filter(qtype=terms["qtype"])
    if terms["status"] == "blocked":
        rows = rows.filter(blocked=True)
    elif terms["status"] == "allowed":
        rows = rows.filter(blocked=False).exclude(rcode="")
    elif terms["status"] == "noanswer":
        rows = rows.filter(rcode="")
    return rows, terms


def _context(request: Request, **extra) -> dict:
    rows, terms = _filtered(request)
    page = Paginator(rows, PAGE_SIZE).get_page(request.GET.get("page"))
    # One read for the page, rather than one for each of fifty rows.
    known = dict(Client.objects.values_list("address", "name"))
    context = {
        "page": page,
        "rows": [(row, known.get(row.client, "")) for row in page],
        "terms": terms,
        "query": request.GET.urlencode(),
        "windows": WINDOW_CHOICES,
        "statuses": STATUS_CHOICES,
        "durations": DURATIONS,
        "groups": [group.name for group in Group.objects.configured()],
        "every_zone": EVERY_ZONE,
        "naming": request.GET.get("naming", "").strip(),
        "error": None,
        "note": None,
    }
    return context | extra


def _render(request: Request, context: dict, status: int = 200) -> HttpResponse:
    template = "queries/table.html" if request.htmx else "queries/index.html"
    return render(request, template, context, status=status)


@login_required
@require_http_methods(["GET"])
def index(request: Request) -> HttpResponse:
    return _render(request, _context(request))


@login_required
@require_http_methods(["GET"])
def dashboard(request: Request) -> HttpResponse:
    """The same rows as the log, counted rather than listed.

    The whole panel swaps, chart included. The timeline goes out as JSON for
    Chart.js, and the tables are bars that CSS draws from a percentage.
    """
    window = request.GET.get("window", "").strip()
    if window not in PERIODS:
        window = DEFAULT_PERIOD
    span, kind = PERIODS[window]
    since = timezone.now() - span
    over_time = stats.timeline(since, kind)
    # The window bounds the buckets, so the chart already holds the totals.
    stopped = sum(over_time["blocked"])
    total = sum(over_time["allowed"]) + stopped
    context = {
        "window": window,
        "periods": PERIOD_CHOICES,
        "since": since,
        "timeline": over_time,
        "blocked": stats.top(since, blocked=True),
        "allowed": stats.top(since, blocked=False),
        "clients": stats.clients(since),
        "total": total,
        "stopped": stopped,
        "share": 100 * stopped / total if total else 0,
    }
    template = "queries/summary.html" if request.htmx else "queries/dashboard.html"
    return render(request, template, context)


@login_required
@require_http_methods(["POST"])
def rule(request: Request) -> HttpResponse:
    """Block or allow one name, from the row that shows it."""
    try:
        domain = normalize(request.POST.get("domain", ""))
    except InvalidDomain as problem:
        return _render(request, _context(request, error=str(problem)), status=422)
    action = request.POST.get("action", "")
    if action not in {Action.BLOCK.value, Action.ALLOW.value}:
        return _render(request, _context(request, error="Unknown action."), status=422)

    zones = list(Group.objects.configured())
    chosen = request.POST.get("group", "")
    targets = zones if chosen == EVERY_ZONE else [z for z in zones if z.name == chosen]
    if not targets:
        return _render(request, _context(request, error="Choose a zone."), status=422)

    seconds = request.POST.get("duration", "")
    expires_at = (
        timezone.now() + timedelta(seconds=int(seconds)) if seconds.isdigit() else None
    )
    # One rule for each name in each zone. A second click replaces the first,
    # so blocking then allowing does what it looks like.
    for group in targets:
        Rule.objects.update_or_create(
            group=group,
            domain=domain,
            defaults={
                "action": action,
                "source": Source.QUERY_LOG,
                "expires_at": expires_at,
                "note": "From the query log",
            },
        )
    verb = "blocked" if action == Action.BLOCK.value else "allowed"
    where = "every zone" if len(targets) > 1 else targets[0].name
    # The worker tells unbound. This page only records what the rule is.
    jobs.nudge("transfer")
    return _render(request, _context(request, note=f"{domain} is {verb} in {where}."))


@login_required
@require_http_methods(["POST"])
def client(request: Request) -> HttpResponse:
    """Give an address a name, from the row that shows it.

    An empty name removes the row, so a name can be taken back.
    """
    address = request.POST.get("address", "").strip()
    name = request.POST.get("name", "").strip()
    try:
        ipaddress.ip_address(address)
    except ValueError:
        return _render(
            request,
            _context(request, error=f"{address} is not an address."),
            status=422,
        )
    if name:
        Client.objects.update_or_create(address=address, defaults={"name": name})
        note = f"{address} is {name}."
    else:
        Client.objects.filter(address=address).delete()
        note = f"{address} has no name now."
    return _render(request, _context(request, note=note))
