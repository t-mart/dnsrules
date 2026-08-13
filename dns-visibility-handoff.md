# Handoff: DNS log and control plane

This document hands off `dnsrules` to a separate repository: a website that
shows DNS activity on the home network, and that blocks or unblocks names from
the same page.

`dnsrules` names the project, the system user it runs as, and the group that
reaches unbound.

The router, `mace`, is configured by the `mace` Ansible repository. This
document tells you what `mace` provides today, what `mace` must still change,
what you must not touch, and what is undecided.

## The goal

One website, on the home network, with three parts.

1. **A log table.** Every resolution: time, which host asked, the name, the
   type, the answer, and whether a policy blocked it. Filters on each field.
2. **Controls in that table.** Block or unblock any row, temporarily or
   permanently.
3. **A rules page.** Everything `dnsrules` currently blocks or unblocks, marked
   temporary or permanent, with edits and removals.

`dnsrules` owns one RPZ zone file and puts every rule there, temporary and
permanent alike. Expiry is an application concern, not a DNS concern.

## Prior art: copy Pi-hole's screens, not its architecture

Pi-hole solved this display problem years ago. Do not invent new screens. Take
its layout as the specification and spend the effort on the parts that differ.

Worth copying:

- The query log table: time, client, type, domain, status, upstream, and reply
  time, with a filter on each column.
- The client breakdown, and top blocked and top allowed names over a window.
- The allow and deny list page.
- The global pause. Pi-hole disables blocking for 5 minutes from one button.
  Here that is `unbound-control rpz_disable privacy_blocklist` plus a timer to
  re-enable. Cheap, and a good panic button.

Do not copy its data model. `mace` already does things Pi-hole cannot, and the
differences run the other way:

- Pi-hole is dnsmasq and has no views. `mace` resolves `gothere.dev` per client
  scope and returns NODATA for the Firefox canary on selected hosts. Any design
  that puts a filter in front of unbound hides the real client address and
  breaks all of it.
- Pi-hole keeps lists, groups, and clients in `gravity.db`, a SQLite file. Here
  the rules are text files that git can diff, and that is deliberate.

The one screen Pi-hole does not have is the one that started this project: a
per-domain unblock with an expiry. That is the part to design carefully.

## Interfaces

Four, and they are enough.

| Interface                                   | Direction | Purpose                        | Ready?            |
| ------------------------------------------- | --------- | ------------------------------ | ----------------- |
| dnstap socket                               | read      | every query and answer         | **no, see below** |
| journald, `unbound` unit                    | read      | which policy blocked, and why  | yes               |
| `/etc/unbound/zones/rpz-runtime-rules.zone` | write     | the rules                      | yes               |
| `unbound-control` socket                    | write     | reload the zone, read counters | yes               |

Plus one optional input: a host map rendered by Ansible, to print names instead
of addresses.

### 1. The full query log needs dnstap, which is not on yet

This is the blocker. `mace` logs RPZ matches only. A block produces a line; a
normal resolution produces nothing. The log table you want does not exist yet.

unbound on `mace` is built with `--enable-dnstap`. dnstap emits every client
query and every client answer as structured binary messages over a socket, or
over TCP to another host. It covers cache hits, because it taps the client
interface, not the resolver.

Turning it on is a `mace` change, tracked in that repo's `TODO.md`. Sequence it
with your ingest service: dnstap with no consumer is waste. Do not ask for
`log-queries` instead. It is unstructured text and it floods journald.

The options to expect are `dnstap-enable`, `dnstap-socket-path` or `dnstap-ip`,
`dnstap-log-client-query-messages`, and `dnstap-log-client-response-messages`.
Confirm the exact names against `unbound.conf(5)` on `mace`. The playbook runs
`unbound-checkconf` before it writes the config, so a wrong name fails the
deploy instead of the router.

Those two message types fill every column of the Pi-hole style table except
two. Reply time comes from the gap between the client query and the client
response, so keep both. The upstream column needs
`dnstap-log-forwarder-query-messages` as well, and those messages do not carry
the client, so the join back is awkward. Treat that column as optional.

**dnstap writes nothing to disk.** It is a stream, not a log file. unbound
encodes each message and hands it to the open socket or TCP connection. There is
no spool and no local copy, so turning dnstap on adds no storage on `mace` and
nothing to rotate. If no consumer is listening, unbound retries the connection
and drops messages in the meantime. A slow or absent consumer loses records; it
does not block resolution and it does not fill the disk. That is the right
failure mode for a router, and it means every retention decision is yours.

Three design notes:

- unbound is chrooted to `/etc/unbound` and drops privileges to the `unbound`
  user. A unix socket path must be reachable and connectable under those
  constraints. Test it before you depend on it.
- Prefer `dnstap-ip` at `127.0.0.1`. `dnsrules` listens, unbound connects out,
  and the chroot never enters into it. A unix socket has to sit inside
  `/etc/unbound` and be connectable by the `unbound` user, which is solvable but
  is work for no gain.
- Do not send the stream off the box in the clear. It is every DNS query in the
  house, and it is a better browsing history than anything the blocklist stops.
  On loopback this is moot, which is another reason to keep it there.

A dnstap client response carries the whole answer message, so you get the rcode,
the RA bit, and the records. That is enough to show a row and mark it blocked.
It does not say **which** list blocked it. For that, join the RPZ log.

### 2. The RPZ match log says which policy acted

Unbound writes one line per RPZ match to syslog. The lines reach journald under
the `unbound` unit.

Example, as `journalctl --output cat` shows it:

```
[32550:0] info: rpz: applied [runtime_rules] google-analytics.com. rpz-passthru 127.0.0.1@43605 google-analytics.com. A IN
```

Fields after the `[pid:thread] info:` prefix:

| Field  | Example                 | Meaning                        |
| ------ | ----------------------- | ------------------------------ |
| zone   | `runtime_rules`         | which RPZ zone matched         |
| rule   | `google-analytics.com.` | the entry inside that zone     |
| action | `rpz-passthru`          | what unbound did               |
| client | `127.0.0.1@43605`       | client address and source port |
| qname  | `google-analytics.com.` | the name the client asked for  |
| qtype  | `A`                     | record type                    |
| qclass | `IN`                    | record class                   |

A tested regular expression:

```
rpz: applied \[(?<zone>[^\]]+)\] (?<rule>\S+) (?<action>\S+) (?<client>[^@]+)@(?<port>\d+) (?<qname>\S+) (?<qtype>\S+) (?<qclass>\S+)
```

Read it with `journalctl --unit unbound --output json --follow`. Backfill with
`--since` at startup, so a restart does not lose the window.

Cautions:

- The blocklist uses qname triggers only, and unbound omits the trigger word for
  those. Other trigger types add one token before the rule. Tolerate it.
- Join to the dnstap rows on time, client address, and qname. There is no shared
  request id.
- The blocked answer also clears the RA bit, because `rpz-signal-nxdomain-ra` is
  on for the blocklist zone. NXDOMAIN with RA cleared means a policy blocked it.
  Use it as a cheap in-band signal when the join fails.

Measured volume is about 88 RPZ lines an hour, near 2,000 a day. journald
rotates, so keep history in your own store.

### 3. The zone file is the rule store

| Order | Zone name                     | File                                                | Owner         |
| ----- | ----------------------------- | --------------------------------------------------- | ------------- |
| 1     | `runtime_rules`               | `/etc/unbound/zones/rpz-runtime-rules.zone`         | **`dnsrules`** |
| 2     | `privacy_blocklist_overrides` | `/etc/unbound/rpz-privacy-blocklist-overrides.zone` | Ansible       |
| 3     | `privacy_blocklist`           | `/etc/unbound/zones/rpz-privacy-blocklist.zone`     | unbound       |

Unbound applies RPZ zones in configuration order, and the first match wins. Zone
1 is yours and it is first, so a rule there beats everything. Ansible creates
the file once, empty, and never rewrites it. Verified: an Ansible run with
entries in the file reports `ok`, not `changed`.

One line per rule. The right hand side selects the action:

| Line                              | Effect                        |
| --------------------------------- | ----------------------------- |
| `example.com CNAME rpz-passthru.` | unblock: skip all later zones |
| `example.com CNAME .`             | block: answer NXDOMAIN        |
| `example.com CNAME *.`            | block: answer NODATA          |
| `example.com A 10.0.0.5`          | answer with your own address  |

A leading `*.` on the left matches subdomains only, so list the bare domain too.
Blocking a name that the feed already blocks is harmless.

Keep expiry in your own state, not in the zone. The format has nowhere to record
it. Treat the zone file as rendered output: write state, render, write the file
atomically, reload. A prune timer every minute is enough.

Validate input before you render, and never build a rule by concatenation. A
malformed line does not always fail loudly. Observed on `mace`: two rules fused
into one line by a lost newline gave

```
google-analytics.com CNAME rpz-passthru.example.com CNAME .
```

`rpz-passthru.example.com` is a legal CNAME target, so unbound loaded the line
without complaint and applied it as `rpz-local-data`, answering with a CNAME to
a name that does not exist. The intent was an unblock. The effect was a block of
another kind, and `auth_zone_reload` still returned `ok`.

So: emit one line per rule, each ending in a newline. Treat the right hand side
as a fixed string chosen from the table above, never as user input. Check the
rendered file before you reload. Reuse the domain pattern in
`vars/schemas/unbound_blocklist.schema.json`.

Read zone 2 as well, read-only, so the rules page shows the whole picture.
`mace` renders it from `vars/unbound_blocklist.yml`. It is the config-as-code
path, it is in git, and it survives a rebuild of the router. Your state does
not, unless you back it up. That is the cost of owning both kinds of rule in one
file, and it is worth naming out loud.

### 4. Reload with no restart

```
unbound-control auth_zone_reload runtime_rules
```

This rereads the file into the running server. No restart. No cache flush. No
Ansible run. The SOA serial does not need a bump.

Verified end to end: a blocked name returned NXDOMAIN, one appended line plus a
reload made it resolve, and removing the line restored the block at once.

Note the ordering property this proves: unbound applies RPZ **before** the
cache. A removed rule takes effect immediately, even though the old answer is
still cached. Downstream clients still hold their own caches, so a browser can
lag by its own TTL. Follow a removal with `unbound-control flush <name>` if you
want to be sure.

Other useful commands:

- `unbound-control stats_noreset` reports `num.rpz.action.*` counters, plus
  rcode and query type breakdowns. `extended-statistics` is on, which those
  need. Counters that are still zero stay hidden.
- `unbound-control rpz_disable privacy_blocklist` turns the whole blocklist off
  for every client. `rpz_enable` reverses it. Good for a panic button.
- `unbound-control status` and `dump_infra` report health and upstream latency.

### 5. Client names

The blocklist and your zone apply to a client only if it carries the
`dns_privacy` tag:

- LAN hosts with `dns_privacy: true` in `vars/hosts.yml`
- every tailnet client, all of `100.64.0.0/10`
- the router itself, `127.0.0.1` and `::1`

An untagged client still appears in dnstap, but never in the RPZ log, because no
RPZ zone applies to it. `tim-switch` and `laura-work-phone` are the current
exceptions.

To turn addresses into names:

- LAN addresses are in `vars/hosts.yml`. A host can have several interfaces,
  each with its own address. Ask the `mace` repo to render this as JSON on the
  router at deploy time. A TODO item covers it. Do not parse the repo from
  another machine.
- `127.0.0.1` is `mace` itself, through `systemd-resolved`.
- Tailnet addresses have no complete map in the repo. Use
  `tailscale status --json` at runtime.

## Constraints

- **Do not write `/etc/unbound/unbound.conf`.** Ansible owns it. A deploy
  overwrites it and restarts unbound.
- **Do not write `/etc/unbound/zones/rpz-privacy-blocklist.zone`.** Unbound owns
  it and rewrites it about every 12 hours. It holds about 430,000 entries, so do
  not try to list it in the UI. Test single names against it instead.
- **Do not write `/etc/unbound/rpz-privacy-blocklist-overrides.zone`.** Ansible
  renders it. Read it.
- **The control socket is `/run/unbound/control.sock`, owned by root,
  mode 0755.** A unix socket needs write permission to connect, and unbound does
  not chmod or chown it. Only root can drive `unbound-control` today.
- **`/etc/unbound/zones` is owned by `unbound`, mode 0750.** An atomic write
  means a temporary file in that same directory, then a rename. That needs write
  permission on the directory. Root has it.
- **unbound is chrooted to `/etc/unbound`.** This is why a state file sits under
  `/etc` instead of `/var/lib`, where it belongs. unbound opens the zone file
  after it chroots, so a path outside that tree resolves inside it and the zone
  fails to load. `/var/lib/unbound` exists and the unbound user can write to it,
  through `StateDirectory=unbound`, but unbound cannot reach it. Only
  `chroot: ""` changes this, and that gives up a layer of defense on the router.

  So make the zone file path **configuration in `dnsrules`, not a constant**.
  If `mace` ever drops the chroot, one setting changes and nothing else.

## Recommended shape

All of `dnsrules` runs on `mace`. One service: it collects dnstap, follows
journald, owns the zone file, calls `unbound-control`, prunes expired rules, and
serves the website.

It listens on the LAN address, and you reach it directly by address and port.
This is LAN first on purpose. It is the tool you want when DNS or the proxy is
broken, so nothing about it may depend on either. A reverse proxy elsewhere adds
a name and TLS on top. The tailnet is a secondary path, not the design centre.

`mace` must open the port. Add it to `input_allow_rules` in `vars/nftables.yml`,
the same way port 9100 is open for the node exporter.

`mace` has 439 GB free and 15 GB of RAM. It is a router by job, not by hardware,
and this workload does not trouble it.

Do not split the collector from the website across two machines. Every interface
in this document is local to `mace`: a file, a unix socket, and the journal.
Moving the website off the box converts all three into a network protocol you
have to design, secure, deploy, and debug, and it buys nothing that a reverse
proxy does not already give you.

The one seam worth keeping is privilege, not machines.

### Nothing has to run as root

Only two operations need privilege: write the zone file, and connect to the
control socket. Both are grantable to a dedicated system user. Root is not
needed anywhere.

The steps, all of them work for `mace` to do:

1. Add a system user and group, `dnsrules`.
2. Put the zone file in its own directory, `/etc/unbound/rules/`, owned
   `dnsrules:unbound`, mode 0750. Make the zone file mode 0640. `dnsrules`
   writes it, and unbound reads it through the group.
3. Add a drop-in for `unbound.service` with an `ExecStartPost` that sets the
   control socket to group `dnsrules`, mode 0770. unbound opens that socket as
   root before it drops privileges, and it never chmods it, so nothing else
   fixes this.
4. Run the service as `dnsrules`, with `SupplementaryGroups=systemd-journal` so
   it can read the unbound journal. Journal access needs a group, not root.

One process is the right start. Note what it means: whoever reaches the website
can write RPZ rules, and a rule can point any name at any address, so this is
not only a blocking control. If that becomes uncomfortable, split the rule
writer into its own unit behind a local socket and run the web process as its
own user. Keep the boundary clean inside the code so that stays a small change.
Do not build the IPC before you want it.

### Authentication

A session cookie, one admin, sessions in memory. Not basic auth: it has no
logout, it replays the password on every request, and it gives you a browser
prompt instead of a page you control.

- Store one password hash, argon2id, in a file that only `dnsrules` reads. Not
  in the repository.
- On login, take 256 bits from the system random source for the session id and
  hold it in a map with an expiry. A restart ends every session. For one person
  on one machine that is correct behaviour, not a limitation, but remember that
  a deploy logs you out.
- Set the cookie `HttpOnly` and `SameSite=Lax`, with no `Domain`. Do **not**
  require `Secure`. Plain HTTP on the LAN has to keep working, because this is
  the tool you reach for when the proxy is down. Set `Secure` per request, only
  when that request already arrived over HTTPS.
- Accept the cost knowingly: over plain HTTP the session cookie crosses the LAN
  in the clear. Keep session lifetimes short and bind the listener to the LAN
  address.
- Keep allowed `Host` values and allowed `Origin` values in server settings, as
  lists, and reject everything else. With `Secure` gone this is the main
  defence, and it stops DNS rebinding against the panel.
- `SameSite=Lax` already stops the cookie on cross site POST, which covers form
  CSRF. Check `Origin` on state changing requests as well.
- Count failed logins in the same map and slow them down.

### Stack

Python, with Django for the web half.

This project is roughly one fifth website and four fifths daemon, so weigh the
daemon first. It has to decode a framestreams and protobuf byte stream, follow
the journal, run `unbound-control`, write a file atomically, and keep a timer.
Python does all of that, and existing dnstap receiver libraries are worth a look
before writing the framing by hand.

Django then supplies the boring half at no cost: session auth, the allowed
`Host` and `Origin` lists as settings, an ORM with migrations, and templates.
Those are the settings described above, already built.

Shape it as two systemd units over one codebase. `manage.py` runs the web
server; a second unit runs an ingest command that shares the models. Both run as
`dnsrules`.

Use the existing Postgres server for the query log. It suits this workload
better than SQLite: heavy append, analytical reads, and time based deletes.
Django treats Postgres as its first class backend, `GenericIPAddressField` maps
to `inet`, and `date_trunc` plus `INSERT ... ON CONFLICT` make the rollups
short. Batch the inserts on a one second tick rather than one statement per
message.

Keep rule state in Postgres too, not in a second file. Two tabs, the web
workers, and the prune timer all write rules, and a file makes that a
read-modify-write race that you have to solve with locking. A transaction solves
it for free, and the rules page can then join against the log to show how often
each rule fires.

DNS does not depend on the database, whatever happens here. unbound reads the
zone file, and that file persists on disk. Postgres holding the rules means the
zone file is rendered output, exactly as before.

Three invariants make that safe:

- **Never render the zone file from an unreachable or empty database.** On
  startup, reconcile only after a successful read. A naive render at boot with
  no connection writes an empty zone and silently drops every rule.
- **Take `pg_advisory_lock` around render, write, and reload.** Two workers
  rendering at once interleave their writes. This is the one lock you need, and
  it lives in the store you already have.
- **Write the file atomically**, temporary file then rename, then reload.

What a database outage costs: no rule changes from the UI, and expiries stop
firing, so a temporary unblock outlives its window. Both are recoverable, and
the escape hatch is the manual recipe at the end of this document. Neither
affects resolution.

For the table, use server rendered templates with htmx. The UI is filters and a
table. It does not pay for a build step.

Rejected, with reasons:

- **Full stack JavaScript.** The instinct is right. There is no dnstap library
  worth trusting, so the framing and protobuf become yours, and journal access
  means spawning `journalctl` and parsing it. The gain would be a richer UI,
  which is not what this needs.
- **Go** is the strongest technical fit and the honourable alternative: the
  reference dnstap implementation is Go, it is one static binary, and stream
  plus HTTP in one process is natural. It costs sessions, migrations, and
  templates, all written by hand. Choose it if the Python dnstap side turns
  painful, or if one binary matters more than fewer lines.

## Retention

Retention is entirely your policy. Nothing upstream keeps anything for you.
journald rotates the RPZ lines, and dnstap keeps nothing at all.

Measure before you size anything. Sample the counter one minute apart:

```nu
sudo unbound-control stats_noreset | find total.num.queries
```

Two stores with different lifetimes:

- **Raw rows**, one per query. This is what the log table filters over. Keep 30
  days. Partition the table by day, and drop the old partition instead of
  deleting rows. A `DROP` is instant and leaves nothing to vacuum, which is the
  main reason this is easier on Postgres than on SQLite. Index the timestamp
  with BRIN: the data arrives in time order, so the index stays tiny.
- **Hourly rollups**: client, registrable domain, blocked or not, and a count.
  This is what the graphs and the top-blocked lists read. Keep 13 months, so
  year over year comparison works.

Roll up first, then delete the raw rows, nightly. For reference, Pi-hole keeps
its long term database one year by default, and that database is the thing that
grows.

Add a size cap as a backstop, and drop oldest first when it trips. One
misbehaving device turns into millions of rows fast.

If the Postgres server is on another machine, two things follow.

Put TLS on the connection. This table is every DNS query in the house, and
sending it in clear text across the LAN undoes the point of the blocklist. Use
`sslmode=verify-full`. Plain `require` encrypts but verifies nothing, so it
stops a sniffer and not an impostor.

Give the database host a name in `vars/dns_hosts.yml`, so it resolves to its LAN
address for LAN clients through the existing split horizon. Then a public Let's
Encrypt certificate for that name verifies against the system CA bundle, with no
private CA to distribute.

Expect to lose log rows while that machine is down. The ingest has nowhere to
buffer them, and dnstap drops rather than blocking unbound. That is the right
direction to fail.

## Open questions

- **Which port, and whether the tailnet reaches it too.** LAN first is decided.
  Both need a rule in `vars/nftables.yml`.
- **Who deploys the service to `mace`.** Either the `mace` playbook grows tasks
  for it, or this project deploys itself. Ansible owns everything in
  `/etc/unbound` today.

## What mace must still do

Tracked in that repo's `TODO.md`, under "Work that returns here".

1. Turn on dnstap. Blocks the log table.
2. Render a client address to name map as JSON on the router.
3. Grant the service access to the control socket and the zone directory, if it
   does not run as root.

## Verification recipe

Run on `mace`, as root. This exercises the control path by hand. It is the test
`dnsrules` must reproduce.

```nu
q google-analytics.com A @127.0.0.1 --format=json | from json | get 0.replies.0.rcode
echo "google-analytics.com CNAME rpz-passthru." | sudo tee --append /etc/unbound/zones/rpz-runtime-rules.zone
sudo unbound-control auth_zone_reload runtime_rules
q google-analytics.com A @127.0.0.1 --format=json | from json | get 0.replies.0.rcode
journalctl --unit unbound --since "-1 min" --output cat | find runtime_rules
```

Expect rcode 3, then rcode 0, and one `rpz-passthru` log line. To undo, delete
the line and reload again.

A blocked answer also has the RA bit cleared:

```nu
q google-analytics.com A @127.0.0.1 --format=json | from json | get 0.replies.0 | select rcode recursionavailable
```
