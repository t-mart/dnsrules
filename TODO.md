# TODO

Build order for `dnsrules`. See [the handoff](dns-visibility-handoff.md) for the
interfaces, the constraints, and the reasoning behind each choice.

Order matters here. dnstap is not on yet, and it blocks only the query log. The
rules half needs nothing new from the router, so build it first and ship a
useful tool before the log exists.

## 0. Skeleton

- [x] Django project, src layout, `uv_build`, `dnsrules` console script
- [x] htmx 4 vendored, no CDN and no Node.js
- [x] Tailwind 4 through django-tailwind-cli, compiled output committed
- [x] Env-driven settings that import with an empty environment
- [x] argon2 password hashing, session auth, LAN cookie policy
- [x] WhiteNoise serving from the finders, no collectstatic step
- [x] `just check` pipeline and smoke tests

## 1. Rules

The write path. It needs Postgres and the router, not dnstap.

- [x] Reach Postgres and record the setup in the README. It is on `bayleaf`,
      not local, and the test role needs `CREATEDB`
- [x] Validate the domain against the pattern in
      `vars/schemas/unbound_blocklist.schema.json` from the `mace` repo
- [x] `unbound/zone.py`: render rules to zone text, then write atomically
- [x] Read the SOA header back out of the zone file, so it cannot drift from
      the one Ansible writes
- [x] Choose the right hand side from a fixed table. Never concatenate user
      input into a rule line
- [x] Test the fused-line case: two rules joined by a lost newline load without
      complaint and invert the intent
- [x] `unbound/control.py`: talk to the control socket, run `auth_zone_reload`
- [x] Make the zone file path a setting, not a constant. unbound is chrooted
      today and that may change
- [x] `Rule` model: domain, action, source, expiry, note, timestamps
- [x] `rules/services.py`: reconcile under `pg_advisory_lock`, then render,
      write, and reload
- [x] Refuse to render when the database read fails. An empty render silently
      drops every rule
- [x] `prune` and `reconcile` management commands
- [ ] Run `prune` from a timer every minute
- [ ] Rules page: list, add, edit, remove, with htmx
- [ ] Read `privacy_blocklist_overrides` read-only, so the page shows the whole
      picture

## Fixtures: capture, never invent

Three interfaces carry a wire format this project does not control: the RPZ log
lines, the dnstap stream, and the control socket. A generator written here
tests the decoder against its own assumptions, so a shared misreading of the
format passes every test and fails on the router.

So capture real bytes from `mace` once, commit them, and replay them. Synthesize
only to build a case that capture cannot reach, such as a truncated frame.

- [ ] Capture `journalctl --unit unbound --output json` lines that cover each
      RPZ action, and commit them
- [ ] Capture a dnstap framestream to a file, and commit a short one
- [ ] Record the capture commands in the README, so a fixture can be refreshed

The control socket is the exception. Its protocol is one line of text, so the
tests already run a real unix socket and assert the bytes on the wire.

## 2. RPZ match log

journald carries these today, so this needs nothing from `mace`.

- [ ] `unbound/journal.py`: follow `journalctl --unit unbound --output json`
- [ ] Parse with the tested regular expression in the handoff
- [ ] Backfill with `--since` at startup, so a restart loses no window
- [ ] Tolerate the extra token that non-qname triggers add
- [ ] Model and store the matches

## 3. Query log ingest

Blocked. `mace` must turn dnstap on first.

- [ ] Wait for dnstap on `mace`, over `dnstap-ip` at `127.0.0.1`
- [ ] `unbound/dnstap.py`: decode framestreams and protobuf. Look for an
      existing receiver library before writing the framing by hand
- [ ] Keep client query and client response messages. Reply time is the gap
      between them
- [ ] `ingest` management command, batching inserts on a one second tick
- [ ] Join to the RPZ matches on time, client address, and qname
- [ ] Fall back to the in-band signal when the join fails: NXDOMAIN with the RA
      bit cleared means a policy blocked it

## 4. Query log table

- [ ] Partition the raw table by day. Index the timestamp with BRIN
- [ ] Columns: time, client, type, domain, status, upstream, reply time
- [ ] A filter on each column
- [ ] Block and unblock controls on each row, temporary or permanent
- [ ] Hourly rollups: client, registrable domain, blocked or not, and a count
- [ ] Retention: 30 days raw, 13 months of rollups
- [ ] Nightly job: roll up first, then drop the old partition
- [ ] Size cap as a backstop, oldest first when it trips
- [ ] Measure the query rate before sizing anything

## 5. Dashboard

- [ ] Top blocked and top allowed over a window, as CSS bars
- [ ] Client breakdown, as CSS bars
- [ ] Global pause: `rpz_disable privacy_blocklist` plus a timer to re-enable
- [ ] Queries over time. Choose a chart library at this point, not before.
      uPlot if it stays a time series, Observable Plot if the dashboard grows
      more chart types
- [ ] Keep chart elements outside the htmx swap target, and use `htmx.onLoad()`
      for anything inserted later

## 6. Client names

- [ ] Wait for `mace` to render the host map as JSON on the router
- [ ] Read tailnet names from `tailscale status --json` at runtime
- [ ] Map `127.0.0.1` to `mace`
- [ ] Show the address when no name is known

## 7. Packaging and deployment

- [ ] `serve` management command wrapping gunicorn through its Python API
- [ ] `systemd` management command that prints, and never installs:
  - [ ] `dnsrules-migrate.service`, oneshot, with `RemainAfterExit=yes`
  - [ ] `dnsrules-web.service` and `dnsrules-ingest.service`
  - [ ] `sysusers.d` entry for the `dnsrules` user, including `m dnsrules unbound`
  - [ ] `tmpfiles.d` entry for `/etc/dnsrules` and the zone directory
  - [ ] `unbound.service` drop-in that chmods the control socket
- [ ] Generate a `SECRET_KEY` into `/etc/dnsrules/dnsrules.env` at install time.
      More than one web worker needs it
- [ ] Version from git tags, so `uv tool install` from a branch reports
      something real
- [ ] Write the install and upgrade procedure in the README
- [ ] Back up the rule state. The router survives a rebuild through Ansible.
      Your Postgres rows do not

## Waiting on the mace repo

Tracked there under "Work that returns here".

| Item | Blocks |
| --- | --- |
| Turn on dnstap | section 3 and everything after it |
| Render the client address to name map as JSON | section 6 |
| Create the user, and grant the socket and zone directory | section 7 |
| Open the port in `vars/nftables.yml` | reaching the site at all |

## Open questions

- [ ] Which port, and whether the tailnet reaches it. LAN first is decided
- [ ] Public or private GitHub repository. A private one makes
      `uv tool install` need a deploy key on the router
- [ ] Whether the Django admin stays. It is useful for poking at rows, and it is
      a second way into the same power
