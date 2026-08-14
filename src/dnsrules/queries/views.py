"""The query log screen.

One table, a filter on each column, and a control on each row. The control is
the point of the project: a name you need is blocked, and you unblock it here
without touching a config file.
"""

import logging
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from dnsrules import names
from dnsrules.core import jobs
from dnsrules.hosts import InvalidHosts
from dnsrules.queries.models import Query
from dnsrules.rules import services
from dnsrules.rules.forms import DURATIONS
from dnsrules.rules.models import Group, Rule, Source
from dnsrules.rules.views import Request
from dnsrules.unbound.domain import InvalidDomain, normalize
from dnsrules.unbound.zone import Action

logger = logging.getLogger(__name__)

PAGE_SIZE = 50

WINDOWS = [
    ("15m", "Last 15 minutes", timedelta(minutes=15)),
    ("1h", "Last hour", timedelta(hours=1)),
    ("24h", "Last day", timedelta(days=1)),
    ("7d", "Last week", timedelta(days=7)),
    ("", "Everything", None),
]
WINDOW_CHOICES = [(key, label) for key, label, _ in WINDOWS]
_SPANS = {key: span for key, _, span in WINDOWS}

STATUS_CHOICES = [
    ("", "Any status"),
    ("blocked", "Blocked"),
    ("allowed", "Allowed"),
    ("noanswer", "No answer"),
]


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
    try:
        hosts = services.read_hosts()
        describe = names.directory(hosts, tailnet_names=names.cached_tailnet())
        groups = list(hosts.groups)
    except InvalidHosts as problem:
        logger.warning("No hosts file, so the log shows addresses: %s", problem)
        describe = None
        groups = []
    context = {
        "page": page,
        "rows": [(row, describe(row.client) if describe else None) for row in page],
        "terms": terms,
        "query": request.GET.urlencode(),
        "windows": WINDOW_CHOICES,
        "statuses": STATUS_CHOICES,
        "durations": DURATIONS,
        "groups": groups,
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

    group = Group.objects.filter(name=request.POST.get("group", "")).first()
    if group is None:
        return _render(
            request,
            _context(request, error="Choose a group. That client belongs to none."),
            status=422,
        )

    seconds = request.POST.get("duration", "")
    expires_at = (
        timezone.now() + timedelta(seconds=int(seconds)) if seconds.isdigit() else None
    )
    # One rule for each name in each group. A second click replaces the first,
    # so blocking then allowing does what it looks like.
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
    # The worker tells unbound. This page only records what the rule is.
    jobs.nudge("transfer")
    return _render(
        request, _context(request, note=f"{domain} is {verb} for {group.name}.")
    )
