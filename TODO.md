# TODO

Outstanding work. Each phase leaves the project in a working state.

## Design of record

- dnsrules renders its rules as an RPZ zone and serves them over HTTP. unbound
  fetches that URL. dnsrules writes no file, and it never writes unbound
  configuration.
- A rule change calls `auth_zone_transfer runtime_rules` over the control
  interface, and unbound refetches at once.
- unbound keeps the last fetch on disk and refreshes on the zone SOA. A dnsrules
  outage never unblocks the house. A lost trigger costs one refresh interval,
  not correctness.
- Control runs over TCP to localhost with `control-use-cert: no`. No
  certificates, no unix socket, and no group membership.
- One process serves the site and runs the jobs. The job table is in Postgres.
- unbound keeps the 430k entry blocklist. dnsrules owns every rule a human makes.
- dnstap stays. unbound connects out to the ingest listener.

One rule is one line of the zone:

| Action | Line | Answer |
| --- | --- | --- |
| Block | `<domain> CNAME .` | NXDOMAIN |
| Block with no data | `<domain> CNAME *.` | NOERROR, no answer |
| Allow | `<domain> CNAME rpz-passthru.` | Resolve, and skip every later zone |

The rules zone comes before the blocklist, so an allow beats a block. dnsrules
owns the whole zone text, including the SOA. The serial must rise on each change.

## What the resolver does

Measured against unbound 1.26.0 with `just unbound`. Run it again after an
upgrade, and add a check for each new question.

- Remote control over TCP answers with `control-use-cert: no`, and needs no files.
- RPZ is applied before local zones and before the cache. A local zone of type
  `always_transparent` does not unblock a name that RPZ blocks. Allow rules must
  be RPZ.
- A removed allow takes effect at once, even while the real answer is cached.
- `auth_zone_transfer` refetches on demand. A serial that does not rise leaves
  unbound with what it already has.
- An RPZ block clears the RA bit only where `rpz-signal-nxdomain-ra: yes` is set.
  `CNAME *.` answers NOERROR, which no rcode tells apart from an empty answer.
- unbound holds 430k local zones in 141 MB and answers from them in 0 ms, but a
  bulk load stalls DNS for about 3 seconds. unbound keeps the blocklist for this
  reason, and because it already fetches, refreshes, and persists it.
- `view-first: yes` sends a view client to the global zones when the view holds
  no match. mace sets it on every view, so one rule set reaches every client.

## 1. Serve the rules zone

Done, and checked end to end against `just unbound`: a rule in Postgres reached
the resolver, and an allow rule beat the feed.

- [x] `/rpz/<group>.zone` renders the active rules as RPZ zone text. No
      authentication, because unbound cannot sign in.
- [x] Own the SOA. `Group.serial` holds it, and a change raises it.
- [x] `unbound/control.py`: connect over TCP with no TLS, and send
      `auth_zone_transfer`.
- [x] Trigger a transfer after a rule change. Report a failure on the rules
      page, and say that the rule is saved and lands at the next refresh.
- [x] Keep the domain validator and the fixed right-hand-side table.
- [x] Delete the zone file writer, `DNSRULES_ZONE_MODE`, and their tests.
- [ ] Add `use-application-dns.net` as a block-with-no-data rule, by hand, once
      mace serves a group. It is the Firefox DoH canary, and it moves here out
      of the `firefox_doh_disabled` view. This applies it to every client, where
      today it reaches only the hosts that Ansible flags.

One rule set for the house is the shape the design of record describes, but a
rule still belongs to a group and each group gets its own zone and its own URL.
That costs nothing today and it removes the surprise of a group's rules reaching
clients outside it. Phase 9 adds the tags that make a group mean something.

## 2. One process, jobs in Postgres

- [x] `Job` model: name, run_at, last_run, last_error. The interval lives in
      `SCHEDULE`, because it is code, not data.
- [x] Claim with `FOR UPDATE SKIP LOCKED`, run, then set the next `run_at`. The
      lock is held for the whole run.
- [x] A failed job comes back after `RETRY`, not at its next turn.
- [x] Three jobs: transfer, prune, retention.
- [x] A rule edit sets `run_at = now()` on the transfer job. Only the worker
      talks to unbound, and the page reads `last_error`.
- [x] `serve`: one gunicorn worker, with the jobs and the ingest started from
      `post_worker_init` so nothing is inherited across the fork.
- [x] `worker` command, for development next to `runserver`.
- [x] Delete `src/dnsrules/units/`, the `units` command, and `test_units.py`.
- [ ] Run migrations at startup, so a deploy needs no separate step.

## 3. Scrap the archive

- [x] Drop `queries_hour` and `queries_top`, `rollups.py`, and `partitions.py`.
- [x] Drop the `rollup` and `partitions` commands, and their tests.
- [x] One unpartitioned table, with the BRIN index declared on the model.
- [x] `queries.services.retention` is one DELETE past 30 days.
- [x] Drop `DNSRULES_LOG_MAX_BYTES`.
- [x] Delete the migrations and generate one initial per app. The hand written
      partition SQL went with them.

## 4. Mark a row blocked

Done. Measured with `just probe`, against unbound 1.26.0:

| Case | rcode | AA | RA |
| --- | --- | --- | --- |
| Feed block, `rpz-signal-nxdomain-ra: yes` | NXDOMAIN | yes | **no** |
| Rule `CNAME .`, same option | NXDOMAIN | yes | **no** |
| Rule `CNAME *.` | NOERROR | yes | yes |
| Ordinary answer | NOERROR | no | yes |
| `.invalid`, a built in local zone | NXDOMAIN | yes | yes |

- [x] A cleared RA bit is the only usable in-band signal. AA is not: unbound
      sets it for every local zone, including the LAN names and `.invalid`.
- [x] `CNAME *.` has no in-band signal at all. NODATA reads exactly like a
      legitimate empty answer, so the rules table is the only way to see one.
- [x] `Query.blocked_by` holds `rule` or `feed`, stamped at ingest. A rule is
      matched against the table and is exact. The signal covers the feed.
- [x] The rule set is cached for a minute, so 250,000 rows a day cost one read.
- [x] The log says which one stopped a row.

## 5. Clients in the UI

- [x] `Client` model: address and name. Click a client in the query log to name
      it, and clear the name to take it back.
- [x] Groups moved into the database, with the RPZ zone name on the row. A
      migration adds one group, `home`.
- [x] Delete `hosts.py`, `names.py`, `DNSRULES_HOSTS_PATH`, the tailscale
      subprocess, and the `hosts` recipe.

The unmanaged marking went with `hosts.yml`. It said that no policy reaches a
client, which dnsrules read from the networks in that file. unbound decides it,
through `access-control-tag`, and no control command reports it. Bring it back
only if the question comes up in use.

## 6. Plain CSS

- [x] `src/dnsrules/static/dnsrules/app.css`, written by hand. Elements carry
      the styling, and a class appears only where the markup cannot say what a
      thing is.
- [x] Delete `django-tailwind-cli`, `assets/app.css`, `.django_tailwind_cli/`,
      and the `css`, `css-watch`, and `css-check` recipes.
- [x] A test that every class a template uses is defined in the stylesheet.
      Tailwind generated a rule for whatever a template named, so a typo was
      invisible. Nothing generates one now.

## 7. Docker

- [ ] One image, one process. Development still runs without it.
- [ ] Reach unbound over the compose network, never over `0.0.0.0`.
- [ ] Fold `dev/` into the compose file, so one command brings up both.

## 8. Dashboard

- [ ] Top blocked and top allowed over a window, as CSS bars.
- [ ] Client breakdown, as CSS bars.
- [ ] Queries over time. Choose a chart library at this point, not before.
- [ ] Keep chart elements outside the htmx swap target. Use `htmx.onLoad()` for
      anything inserted later.

## 9. Groups, deferred

Per-client rules need unbound views, and a view is configuration, so Ansible
defines it. Each group then needs its own RPZ zone and its own URL. Nothing here
starts until one rule set for the house is not enough.

## What mace must do

| Item | Blocks |
| --- | --- |
| Enable remote control on `127.0.0.1` with `control-use-cert: no` | phase 1 |
| Point the `runtime_rules` RPZ zone at `/rpz/<group>.zone`. Keep its `zonefile` | phase 1 |
| Remove `dont_block` and the `privacy_blocklist_overrides` zone | phase 1 |
| Set `rpz-signal-nxdomain-ra: yes` on `runtime_rules`, as the feed has | phase 4 |
| Remove the `firefox_doh_disabled` view | phase 1 |
| Uncomment the `dnstap` block. It is off in the template today | the query log |
| Open the website port in `vars/nftables.yml` | reaching the site |

## Open questions

- [ ] Which port, and whether the tailnet reaches it. LAN first is decided.
- [ ] Public or private GitHub repository. A private one needs a deploy key on
      the router.
- [ ] Whether the Django admin stays. It is a second way into the same power.
