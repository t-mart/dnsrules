"""The rules page.

Every mutation answers with the whole panel. The panel is small, and one
rendering path removes a class of partial update faults.
"""

import logging
from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods
from django_htmx.middleware import HtmxDetails

from dnsrules.core import jobs
from dnsrules.core.models import Job
from dnsrules.hosts import Hosts, InvalidHosts
from dnsrules.rules import services
from dnsrules.rules.forms import RuleForm
from dnsrules.rules.models import Group, Rule

logger = logging.getLogger(__name__)


class Request(HttpRequest):
    """The middleware adds `htmx`. Declaring it keeps the type checker honest."""

    htmx: HtmxDetails


def _sections(entries: Hosts) -> list[dict]:
    """Groups in `hosts.yml` order, then any stale group that holds rules.

    Only active rules. A rule past its expiry is out of the zone file already,
    and the next prune deletes the row.
    """
    rules = defaultdict(list)
    for rule in Rule.objects.active().select_related("group"):
        rules[rule.group.name].append(rule)
    sections = [
        {"name": name, "stale": False, "rules": rules[name]} for name in entries.groups
    ]
    sections += [
        {"name": group.name, "stale": True, "rules": rules[group.name]}
        for group in services.stale_groups(entries)
        if rules[group.name]
    ]
    return sections


def _context(entries: Hosts, **extra) -> dict:
    groups = Group.objects.filter(name__in=list(entries.groups))
    context = {
        "sections": _sections(entries),
        "form": RuleForm(groups=groups),
        "edit_form": None,
        "editing": None,
        "error": None,
    }
    return context | extra


def _render(request: Request, context: dict, status: int = 200) -> HttpResponse:
    template = "rules/panel.html" if request.htmx else "rules/index.html"
    return render(request, template, context, status=status)


def _reconcile() -> str | None:
    """Ask the worker to tell unbound. Returns the last failure, if any.

    The page never reaches unbound itself. It sets the job due and reads what
    the last run did, so a resolver that is slow or down cannot hold up a save.
    """
    jobs.nudge("transfer")
    job = Job.objects.filter(name="transfer").first()
    if job is None or not job.last_error:
        return None
    return (
        f"The rule is saved, but the last transfer to unbound failed: "
        f"{job.last_error}. It applies within the hour regardless."
    )


@require_http_methods(["GET"])
def rpz(request: HttpRequest, name: str) -> HttpResponse:
    """One group's RPZ zone, as unbound fetches it.

    No authentication, because unbound cannot sign in. The response names every
    domain the house blocks, so keep the site off the open internet.
    """
    group = get_object_or_404(Group, name=name)
    return HttpResponse(services.zone_text(group), content_type="text/plain")


@login_required
@require_http_methods(["GET", "POST"])
def index(request: Request) -> HttpResponse:
    try:
        entries = services.read_hosts()
    except InvalidHosts as problem:
        return _render(request, {"error": str(problem)}, status=503)
    # A deploy adds a group to `hosts.yml`. Give it a row here, so a rule can
    # point at it without waiting for the next reconcile.
    services.sync_groups(entries)
    if request.method == "GET":
        return _render(request, _context(entries))
    form = RuleForm(
        request.POST, groups=Group.objects.filter(name__in=list(entries.groups))
    )
    if not form.is_valid():
        return _render(request, _context(entries, form=form), status=422)
    form.save()
    return _render(request, _context(entries, error=_reconcile()))


@login_required
@require_http_methods(["GET", "POST", "DELETE"])
def rule(request: Request, pk: int) -> HttpResponse:
    target = get_object_or_404(Rule, pk=pk)
    try:
        entries = services.read_hosts()
    except InvalidHosts as problem:
        return _render(request, {"error": str(problem)}, status=503)
    groups = Group.objects.filter(name__in=list(entries.groups))
    if request.method == "DELETE":
        target.delete()
        return _render(request, _context(entries, error=_reconcile()))
    if request.method == "GET":
        form = RuleForm(instance=target, groups=groups)
        return _render(request, _context(entries, edit_form=form, editing=target.pk))
    form = RuleForm(request.POST, instance=target, groups=groups)
    if not form.is_valid():
        context = _context(entries, edit_form=form, editing=target.pk)
        return _render(request, context, status=422)
    form.save()
    return _render(request, _context(entries, error=_reconcile()))
