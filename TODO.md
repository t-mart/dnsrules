# TODO

Build order for `dnsrules`. See [the design](dns-visibility-handoff.md) for the
interfaces, the constraints, and the reasoning.

Order matters. The rules half needs one `mace` change and nothing else, so it
came first. dnstap is on now, so the query log is next.

## 0. Skeleton

- [x] Django project, src layout, `uv_build`, `dnsrules` console script
- [x] htmx 4 vendored, no CDN and no Node.js
- [x] Tailwind 4 through django-tailwind-cli, compiled output committed
- [x] Env-driven settings that import with an empty environment
- [x] argon2 password hashing, session auth, LAN cookie policy
- [x] WhiteNoise serving from the finders, no collectstatic step
- [x] `just check` pipeline and smoke tests

## 1. The unbound module

Pure code. No Django imports, and no database.

- [x] `unbound/domain.py`: validate against the pattern in
      `vars/schemas/unbound_blocklist.schema.json`
- [x] `unbound/zone.py`: render rules to zone text, then write atomically
- [x] Read the SOA header back out of the zone file, so it cannot drift from
      the one Ansible writes
- [x] Choose the right hand side from a fixed table. Never concatenate user
      input into a rule line
- [x] Test the fused-line case: two rules joined by a lost newline load without
      complaint and invert the intent
- [x] `unbound/control.py`: talk to the control socket, run `auth_zone_reload`

## 2. Rules and groups

The write path. It needs Postgres and the `mace` group change.

- [x] Reach Postgres and record the setup in the README. It is on `bayleaf`,
      not local, and the test role needs `CREATEDB`
- [x] `Rule` model: domain, action, source, expiry, note, timestamps
- [x] `rules/services.py`: reconcile under `pg_advisory_xact_lock`, then render,
      write, and reload
- [x] Refuse to render when the database read fails. An empty render silently
      drops every rule
- [x] `prune` and `reconcile` management commands
- [x] `hosts.py`: read `/etc/dnsrules/hosts.yml`. Never write it
- [x] Treat a missing hosts file as an error. An empty one renders every zone
      file with no rules in it
- [x] `Group` model, keyed by the name in `hosts.yml`
- [x] Add a group to `Rule`. A rule belongs to exactly one group, and a domain
      holds one rule in each group
- [x] Reconcile every group: one file and one `auth_zone_reload` for each
- [x] Replace the zone path and zone name settings. Both now come from
      `hosts.yml`, per group
- [x] Read staleness from `hosts.yml`. A stored flag drifts on the next deploy
- [x] `export` management command: print every rule as YAML, or as JSON
      with `--format json`
- [x] Rules page: list by group, add, edit, remove, with htmx
- [x] Answer 422 for an invalid form, so htmx swaps the errors back in
- [x] Keep a failed reload off the error page. The rule is saved already, so
      the page says so and the next reconcile converges
- [x] Show a stale group, and say that its rules reach no zone file
- [x] Show that a membership change needs an Ansible deploy plus
      `unbound-control reload_keep_cache`
- [x] Run `prune` from a timer every minute. See section 9

## 3. Fixtures: capture, never invent

The RPZ log lines and the dnstap stream carry a format this project does not
control. A generator written here tests the decoder against its own
assumptions, so one shared misreading passes every test and fails on the router.

Capture real bytes from `mace` once and replay them. Synthesize only for a
case that capture cannot reach, such as a truncated frame.

A capture stays out of git when it holds real traffic. The tests that need one
skip without it.

- [x] Capture a dnstap framestream to a file
- [x] Keep the capture out of git. It holds every query the house made during
      the capture window. Tests that need it skip, and pytest runs with `-rs`
      so the skip always prints its reason
- [x] Record the capture recipe in the README, so a fixture can be refreshed

The control socket is the exception. Its protocol is one line of text, so the
tests already run a real unix socket and assert the bytes on the wire.

## 5. Query log ingest

dnstap is on, and a capture is in hand.

- [x] `unbound/framestream.py`: read the frame envelope. Written by hand
      because it is 60 lines of stdlib, and a library would add a dependency
      for that
- [x] `unbound/dnstap.py`: decode the protobuf payload with `protobuf` and
      `dnspython`. `assets/dnstap.proto` is the schema, `just proto` generates
      the module and its stub, and both are committed so an install needs no
      protoc
- [x] Keep client query and client response messages only. The resolver and
      forwarder types carry no client address
- [x] Pair a query with its response, on client, port, name, and type. The key
      repeats, because clients reuse a source port, so each key holds a queue
      and the oldest query takes the next answer
- [x] Read blocked from the in-band signal: NXDOMAIN with the RA bit cleared.
      The journal names the zone as well, and section 2 of the design says why
      that is not worth another interface
- [x] `unbound/receiver.py`: listen, and take one connection after another.
      Each connection is its own frame stream, so a restart of unbound never
      looks like a corrupt frame
- [x] `ingest` management command, batching inserts on a size or a one second
      tick, whichever comes first
- [x] Skip a frame that does not decode. One bad frame must not end a stream

## 6. Query log table

- [x] Partition the raw table by day. Index the timestamp with BRIN
- [x] Columns: time, client, name, type, rcode, blocked, reply time. The
      upstream column needs forwarder messages, which carry no client address.
      It stays out until the rest works
- [x] `partitions` command: make the days ahead, drop the days past retention.
      A DEFAULT partition catches a day nobody made, so no row is ever lost
- [x] A filter on each column: client, name, type, status, and a time window
- [x] Block and unblock controls on each row, temporary or permanent. A second
      click replaces the first rule rather than making a second one
- [x] Hourly rollups, but with no name in them: client, blocked or not, and a
      count. The name was measured and dropped. Keyed on the name, an hour
      holds near 1,600 rows, which is 15 million over 13 months against the 7.5
      million raw rows it replaces. The registrable domain only halves that,
      and it needs the public suffix list to tell `bbc.co.uk` from `co.uk`
- [x] Daily top names instead, blocked and allowed apart, 100 each. The tail is
      what costs, and it is the part nobody reads: in one capture the top 50 of
      162 names covered 64 percent of the queries
- [x] Retention for the raw rows: 30 days, by dropping a partition
- [x] Retention for the rollups: 13 months, by deleting rows. One day of the
      archive is near 600 rows, so a DELETE never has enough to move
- [x] Nightly job: roll up first, then drop the old partition. Two ExecStart
      lines in one oneshot unit, which stops at the first failure
- [x] Size cap as a backstop, oldest first when it trips
- [x] Measure the query rate before you size anything. One 206 second sample
      gave 608 queries, near 2.9 a second. Call it 250,000 rows a day, so 30
      days of raw rows is about 7.5 million

## 7. Dashboard

- [ ] Top blocked and top allowed over a window, as CSS bars
- [ ] Client breakdown, as CSS bars
- [ ] Pause a group: `rpz_disable feed_<group>` plus a timer to re-enable
- [ ] Queries over time. Choose a chart library at this point, not before.
      uPlot if it stays a time series, Observable Plot if the dashboard grows
      more chart types
- [ ] Keep chart elements outside the htmx swap target, and use `htmx.onLoad()`
      for anything inserted later

## 8. Client names

- [x] Name each address from `hosts.yml`. A host has several addresses
- [x] Read tailnet names from `tailscale status --json`, cached for a minute so
      no page view waits on a subprocess
- [x] Mark a client unmanaged when no network in `hosts.yml` covers it. Those
      hosts get no blocking. In the first capture they made 51 percent of the
      traffic, from 3 devices
- [x] Show the address when no name is known
- [ ] `127.0.0.1` needs no rule here. Ansible lists it among mace's own
      addresses. See the mace list below

## 9. Packaging and deployment

- [x] `serve` management command wrapping gunicorn through its Python API
- [x] Ship the units as real files under `src/dnsrules/units/`, in a tree that
      mirrors `/etc`. Generating a unit is for units that depend on runtime
      state, and none of these do. A `units` command copies the tree, and
      `systemctl edit` covers a router that needs a path changed
  - [x] `dnsrules-migrate.service`, oneshot, with `RemainAfterExit=yes`
  - [x] `dnsrules-web.service` and `dnsrules-ingest.service`
  - [x] `dnsrules-prune.service` and `.timer`, every minute. Django ships no
        scheduler, and a timer needs no dependency and no extra process
  - [x] `dnsrules-partitions.service` and `.timer`, daily. It must run days
        ahead of the rows it serves
  - [x] `sysusers.d` entry for the `dnsrules` user, including `m dnsrules unbound`
  - [x] `tmpfiles.d` entry for `/etc/dnsrules`
  - [x] `unbound.service` drop-in that chmods the control socket
- [x] `secret` command that prints a `SECRET_KEY` line for the environment
      file. More than one web worker needs the key, so `serve` refuses to start
      without it
- [x] Write the install and upgrade procedure in the README

## Waiting on the mace repo

| Item | Blocks |
| --- | --- |
| Define the groups: tags, membership, and two `rpz` blocks each | section 2 |
| Create `/etc/unbound/rules/` and each zone file once, group `unbound` and group-writable | section 2 |
| Render `/etc/dnsrules/hosts.yml` from `vars/hosts.yml` | sections 2 and 8 |
| Put the networks in `hosts.yml`: the LAN, the DHCP pool, the tailnet | section 8 |
| List `127.0.0.1` and `::1` among mace's own addresses | section 8 |
| Remove `dont_block` and the overrides zone | section 2 |
| Open port 8000 in `vars/nftables.yml` | reaching the site at all |

## Open questions

- [ ] Which port, and whether the tailnet reaches it. LAN first is decided
- [ ] Public or private GitHub repository. A private one makes
      `uv tool install` need a deploy key on the router
- [ ] Whether the Django admin stays. It is useful for poking at rows, and it is
      a second way into the same power
- [ ] Whether a group needs more than two layers. Two suffice today: the
      dnsrules rules zone, then one feed
