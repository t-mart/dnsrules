# TODO

Outstanding work. Each phase leaves the project in a working state.

## Design of record

- dnsrules renders each rules zone as RPZ text and serves it over HTTP. unbound
  fetches those URLs. dnsrules writes no file, and it never writes unbound
  configuration.
- A rule change calls `auth_zone_transfer <zone>` over the control interface,
  and unbound refetches at once.
- unbound keeps the last fetch on disk and refreshes on the zone SOA. A dnsrules
  outage never unblocks the network. A lost trigger costs one refresh interval,
  not correctness.
- Control runs over TCP to localhost with `control-use-cert: no`. No
  certificates and no unix socket.
- The zone list is deployment configuration, next to `unbound.conf`. The two
  must agree, so one deploy writes both.
- The query log records what an answer was. It never records which policy made
  it that way.
- One process serves the site and runs the jobs. The job table is in Postgres.
- unbound keeps the large blocklist. dnsrules owns every rule a human makes.
- dnstap stays. unbound connects out to the ingest listener.

One rule is one line of the zone:

| Action | Line                           | Answer                             |
| ------ | ------------------------------ | ---------------------------------- |
| Block  | `<domain> CNAME .`             | NXDOMAIN                           |
| Allow  | `<domain> CNAME rpz-passthru.` | Resolve, and skip every later zone |

A dnsrules zone comes before the blocklist, so an allow beats a block. dnsrules
owns the whole zone text, including the SOA. The serial must rise on each
change.

## What dnsrules cannot know

unbound decides which clients a zone reaches, through `tags` and
`access-control-tag`. Nothing reports that back:

- dnstap carries no view, no tag, and no zone. Measured on 1214 real messages:
  no `policy`, no `query_zone`, no `extra`, no `identity`. unbound fills none of
  them, so there is nothing to read.
- Remote control answers `get_option define-tag` and `get_option
  access-control`, but `get_option access-control-tag` comes back empty with
  entries configured, and `get_option view` is an unknown option. No command
  lists views or maps a client to a tag.

Two consequences, both settled:

- Membership stays in `unbound.conf`. dnsrules needs the zone names and nothing
  else.
- An answer cannot be traced to the zone that made it. Phase 1 stops trying.

If a zone on a client is ever wanted, it is a label with the standing of a name,
never an input to policy.

## What the resolver does

Measured against unbound 1.26.0 with `just unbound`. Run it again after an
upgrade, and add a check for each new question.

- Remote control over TCP answers with `control-use-cert: no`, and needs no
  files.
- RPZ is applied before local zones and before the cache. A local zone of type
  `always_transparent` does not unblock a name that RPZ blocks. Allow rules must
  be RPZ.
- A removed allow takes effect at once, even while the real answer is cached.
- `auth_zone_transfer` refetches on demand. A serial that does not rise leaves
  unbound with what it already has.
- `auth_zone_transfer` answers "ok" before it fetches, and answers "ok" when the
  fetch fails. The reply carries no information. `list_auth_zones` reports the
  serial unbound holds, or "no serial" for a zone it never fetched, and the new
  serial lands about 30 ms after the transfer.
- unbound holds 430k local zones in 141 MB and answers from them in 0 ms, but a
  bulk load stalls DNS for about 3 seconds. unbound keeps the blocklist for this
  reason, and because it already fetches, refreshes, and persists it.
- `view-first: yes` sends a view client to the global zones when the view holds
  no match. A deployment that sets it on every view gets one rule set for every
  client.

The flags on an answer, measured with `just probe`:

| Case                                      | rcode    | AA  | RA     |
| ----------------------------------------- | -------- | --- | ------ |
| Feed block, `rpz-signal-nxdomain-ra: yes` | NXDOMAIN | yes | **no** |
| Rule `CNAME .`, same option               | NXDOMAIN | yes | **no** |
| Ordinary answer                           | NOERROR  | no  | yes    |
| `.invalid`, a built in local zone         | NXDOMAIN | yes | yes    |

A cleared RA bit is the only usable in-band signal, and it says that an answer
was blocked. It cannot name the zone. AA is not a signal: unbound sets it for
every local zone, including the LAN names and `.invalid`.

## 1. Stop attributing a block to a policy

Done. `blocked_by` held `rule` or `feed`. The `feed` half read the RA bit, which
is correct. The `rule` half matched the query name against the rules table, and
it was wrong before any of phase 2:

- A wildcard rule never matched. `blocking_domains()` returned `*.example.com`
  verbatim, and the query name is `foo.example.com`.
- A client with no tag gets no RPZ, so its query resolves. dnsrules saw the name
  in the rules table and stamped `rule` anyway.

Many zones would have added a third fault, because a name blocked in one zone
would be stamped for a client in another. Keep "was this blocked", drop "by
what".

- [x] `queries/services.py`: delete `blocking_domains`, `_bucketed`,
      `cached_blocking_domains`, and `RULES_TTL`. `blocked_by()` becomes
      `exchange.blocked`.
- [x] The ingest then imports nothing from the rules app. Keep it that way.
- [x] `queries/models.py`: delete `BlockedBy`. `Query.blocked_by` becomes a
      `blocked` boolean, and the property of that name goes with it.
- [x] Drop the `queries_query_blocked_by` index. Two values give a planner
      nothing that the BRIN on `at` does not already give it.
- [x] `stats.py` and `queries/views.py`: `~Q(blocked_by="")` becomes
      `Q(blocked=True)`.
- [x] `queries/table.html`: drop the muted `rule` or `feed` label under the
      blocked marker.
- [x] One migration for the field and the index. It carries the flag over, so a
      row that read `rule` or `feed` still reads blocked.

The dashboard did not change. Blocked over time, top blocked, and the blocked
share of each client bar all read the boolean.

## 2. Many zones

Done. The schema already carried it: `reconcile()` transferred every group and
confirmed every serial, `rpz()` resolved any name, the rules page sectioned by
group, and two zones ran in the tests. What was missing was a way to declare the
list, and the UI polish.

- [x] `DNSRULES_RPZ_ZONES`, a comma separated list, default `dnsrules`. It
      replaces `RPZ_NAME` and `RPZ_ZONE`.
- [x] Collapse `Group.name` and `Group.zone` into one name. Two names for one
      thing is the drift that `confirm()` had to be written to catch.
- [x] `Group.objects.configured()`: the rows the settings name. Use it in
      `reconcile()`, `rpz()`, `_sections()`, `RuleForm`, and the query log.
- [x] A name dropped from the list stops being served and transferred. Its rules
      stay in the table, because a typo must not delete a rule set.
- [x] `rules/apps.py` seeds a row for each listed name on `post_migrate`. That
      covers `serve`, `just manage migrate`, and the test database alike, so a
      name added to the environment needs nothing done by hand.
- [x] `group=*` on the query log control writes the rule to every configured
      zone, and it is the default. Blocking from a row stays one click.
- [x] The rules page hides the zone picker while one zone is configured.

The htmx endpoints did not change. One migration, to drop the second name.

`reconcile()` raises every serial on each change, so one edit refetches every
zone. That is wasteful and harmless at this size. Scope it to the changed zone
only if a deployment ever runs enough zones to notice.

## 3. The transfer job could never succeed

Done. Found by running the compose stack, not by a test.

`run_due` held the job inside `transaction.atomic()`. `reconcile` raises the
serial, then asks unbound to fetch it, and unbound reads that serial back over
HTTP on another connection. An uncommitted serial is one unbound cannot see, so
the confirmation timed out every time and rolled the bump back. **No rule change
reached the resolver through the worker.** Measured against the running stack:

```
reconcile in autocommit          ok, serial 17
reconcile inside a transaction   FAILED: unbound holds dnsrules at 17, not 18
```

The tests missed it because the fixture answers `auth_zones` from the same
transaction, where the bump is visible. The live check missed it because it
called `reconcile` from a shell, which is autocommit.

- [x] `run_due` claims the row, pushes `run_at` forward, and commits. The job
      then runs outside any transaction, and one more short write records the
      result.
- [x] A test asserts `connection.in_atomic_block` is false inside a job. It
      needs `django_db(transaction=True)`, because the ordinary fixture wraps
      each test in the transaction it is trying to measure.

A job that dies mid run now costs one interval instead of holding the row until
its connection drops. `prune` no longer rolls back its deletes when the transfer
that follows them fails, which is right: the rules are gone, and the zone says
so at the next fetch.

## 4. Deployment

- [x] A healthcheck for each service. The image carries the dnsrules one, so
      `just up` and a bare `docker run` both get it. unbound answers
      `unbound-control status` once it has read its config and bound its ports.
- [x] Run the container as a user other than root. dnsrules writes no file and
      both ports are above 1024, so nothing needed root.
- [x] Decide whether an image is published. No. A deployment installs the wheel
      and runs it under systemd, and `compose.yaml` builds from the repository
      for testing.

## 5. By hand, once a resolver serves a zone

- [ ] Add `use-application-dns.net` as a block rule. It is the Firefox DoH
      canary. As a rule it reaches every tagged client, where a view reaches
      only the flagged hosts.
