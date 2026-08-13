# dnsrules: design and interfaces

`dnsrules` is a website on the home network. It shows DNS activity, and it
blocks or unblocks names from the same page.

`dnsrules` names the project, the system user it runs as, and the group that
reaches unbound.

The router is `mace`. The `mace` Ansible repository configures it. This document
defines what each side owns, what `mace` supplies, and what `dnsrules` must
never touch.

## The goal

One website, with three parts.

1. **A log table.** Every resolution: time, which host asked, the name, the
   type, the answer, and whether a policy blocked it. A filter on each column.
2. **Controls in that table.** Block or unblock any row, temporary or permanent.
3. **A rules page.** Every rule in each group, with edits and removals.

Expiry is an application concern, not a DNS concern. The RPZ format has nowhere
to record it.

## The split between Ansible and dnsrules

Ansible owns identity and structure. dnsrules owns live policy.

| Data | Owner | How to change it |
| --- | --- | --- |
| host name and addresses | Ansible | edit `vars/hosts.yml`, then deploy |
| group names | Ansible | edit Ansible vars, then deploy |
| group membership | Ansible | edit `vars/hosts.yml`, then deploy |
| blocklist feed URL per group | Ansible | edit Ansible vars, then deploy |
| domain allow and deny rules | dnsrules | the website, at once |
| rule expiry | dnsrules | the website, at once |

The rates match the tools. Groups change once a year. Membership changes each
month. Domain rules change each day. A domain rule is the one that must change
in seconds, because it unblocks a site you need right now.

A membership change needs an Ansible deploy and an unbound reload. Show this in
the UI. The inconvenience is real and rare.

**dnsrules writes zone files. It never writes unbound configuration.**

This is the most important rule in this document. A bad zone file makes unbound
skip one zone, and DNS keeps working. A bad configuration file stops unbound
from starting, and the whole house loses DNS.

## Interfaces

| Interface | Direction | Purpose | Ready? |
| --- | --- | --- | --- |
| dnstap socket | read | every query and answer | yes |
| journald, `unbound` unit | read | which policy blocked, and why | yes |
| `/etc/unbound/rules/<group>.zone` | write | the rules | needs the mace change |
| `unbound-control` socket | write | reload a zone, read counters | yes |
| `/etc/dnsrules/hosts.yml` | read | groups, hosts, and names | needs the mace change |

## 1. The query log comes from dnstap

The RPZ log alone is not enough. A block writes a line, and a normal resolution
writes nothing, so it names the blocks and never the traffic.

unbound on `mace` is built with `--enable-dnstap`, and `mace` now turns it on.
dnstap emits every client query and every client answer as structured binary
messages. It covers cache hits, because it taps the client interface, not the
resolver.

Use `dnstap-ip` at `127.0.0.1`. dnsrules listens, and unbound connects out. A
unix socket must sit inside the chroot and stay connectable by the `unbound`
user. That is solvable work for no gain.

The block in `mace`:

```
dnstap:
    dnstap-enable: yes
    dnstap-ip: "127.0.0.1@6000"
    dnstap-tls: no
    dnstap-bidirectional: no
    dnstap-log-client-query-messages: yes
    dnstap-log-client-response-messages: yes
```

Three traps, all verified in the unbound 1.26 source:

- **`dnstap-tls` defaults to yes.** Leave it out and unbound tries TLS against a
  plain socket, so nothing ever arrives.
- **A missing `@port` means port 53.** `extstrtoaddr` takes `UNBOUND_DNS_PORT`
  as its default, so unbound would connect to itself. Always write the port.
- **`dnstap-bidirectional` defaults to yes.** In that mode the receiver must
  answer READY with ACCEPT, and STOP with FINISH. With `no`, unbound sends a
  START control frame and then data frames, and the receiver only reads. That
  is less code here, and it lets a plain socket dump capture a fixture.

Keep client query and client response messages. Reply time is the gap between
the two. The upstream column needs forwarder query messages as well, and those
carry no client address, so the join back is hard. Treat that column as
optional.

**dnstap writes nothing to disk.** unbound encodes each message and hands it to
the open connection. There is no spool and no local copy. If no consumer
listens, unbound retries and drops messages. A slow consumer loses records. It
never blocks resolution and it never fills the disk. Every retention decision is
yours.

Never send this stream off the box in clear text. It is every DNS query in the
house, and it is a better browsing history than the blocklist stops.

A client response carries the whole answer message, so you get the rcode, the RA
bit, and the records. It does not say which list blocked the query. Join the RPZ
log for that.

## 2. The RPZ match log names the policy

unbound writes one line for each RPZ match to syslog. The lines reach journald
under the `unbound` unit.

Example, as `journalctl --output cat` shows it:

```
[32550:0] info: rpz: applied [runtime_rules] google-analytics.com. rpz-passthru 127.0.0.1@43605 google-analytics.com. A IN
```

Fields after the `[pid:thread] info:` prefix:

| Field | Example | Meaning |
| --- | --- | --- |
| zone | `runtime_rules` | which RPZ zone matched |
| rule | `google-analytics.com.` | the entry inside that zone |
| action | `rpz-passthru` | what unbound did |
| client | `127.0.0.1@43605` | client address and source port |
| qname | `google-analytics.com.` | the name the client asked for |
| qtype | `A` | record type |
| qclass | `IN` | record class |

A tested regular expression:

```
rpz: applied \[(?<zone>[^\]]+)\] (?<rule>\S+) (?<action>\S+) (?<client>[^@]+)@(?<port>\d+) (?<qname>\S+) (?<qtype>\S+) (?<qclass>\S+)
```

Read it with `journalctl --unit unbound --output json --follow`. Backfill with
`--since` at startup, so a restart loses no window.

The zone field carries the `rpz-log-name` value, so it tells you which group and
which layer acted.

Cautions:

- Feeds use qname triggers, and unbound omits the trigger word for those. Other
  trigger types add one token before the rule. Tolerate it.
- Join to the dnstap rows on time, client address, and qname. There is no shared
  request id.
- A blocked answer clears the RA bit, because `rpz-signal-nxdomain-ra` is on.
  NXDOMAIN with RA cleared means a policy blocked the query. Use this as a cheap
  signal when the join fails.

Measured volume is about 88 lines an hour, near 2,000 a day. journald rotates,
so keep the history in your own store.

## 3. The zone files

Ansible declares two RPZ zones for each group:

```
rpz:
    name: "rules_kids"
    zonefile: "/etc/unbound/rules/kids.zone"
    tags: "kids"
    rpz-log: yes
    rpz-log-name: "rules_kids"

rpz:
    name: "feed_kids"
    url: "https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/rpz/pro.txt"
    zonefile: "/etc/unbound/zones/feed-kids.zone"
    tags: "kids"
    rpz-log: yes
    rpz-log-name: "feed_kids"
    rpz-signal-nxdomain-ra: yes
```

unbound applies RPZ zones in configuration order, and the first match wins. The
rules zone comes first, so a dnsrules rule always beats the feed. This gives the
layer system: an allow rule exempts a name from the feed, and a deny rule
extends the feed.

A group needs no feed zone. It then carries manual rules only.

Ansible creates each rules zone file once, empty, with `force: false`, and never
rewrites it. dnsrules owns the contents. unbound owns the feed zone files.

Verified against unbound 1.26.0, which `mace` runs:

- `define-tag` adds to the tag list. Several statements accumulate, and a later
  one never replaces an earlier one.
- An `rpz` block accepts several tags on one line, as `tags: "kids guests"`. Two
  groups then share one feed zone, and unbound holds one copy in memory. A
  second `tags:` line replaces the first, so put every tag on one line.
- `reload_keep_cache` exists. Use it for a membership change, so the cache
  survives.

### Rule lines

One line for each rule. The right hand side selects the action:

| Line | Effect |
| --- | --- |
| `example.com CNAME rpz-passthru.` | allow: skip every later zone |
| `example.com CNAME .` | deny: answer NXDOMAIN |
| `example.com CNAME *.` | deny: answer NODATA |
| `example.com A 10.0.0.5` | answer with your own address |

A leading `*.` on the left matches subdomains only. List the bare domain too.
A rule that repeats a feed entry is harmless.

### Never build a line by concatenation

Validate the input before you render. A malformed line does not always fail
loudly. Observed on `mace`, two rules fused into one line:

```
google-analytics.com CNAME rpz-passthru.example.com CNAME .
```

`rpz-passthru.example.com` is a legal CNAME target. unbound loaded the line
without complaint and answered with a CNAME to a name that does not exist. The
intent was an allow. The effect was a deny of another kind, and
`auth_zone_reload` still returned `ok`.

So: emit one line for each rule, and end each line with a newline. Take the
right hand side from the table above, never from user input. Reuse the domain
pattern in `vars/schemas/unbound_blocklist.schema.json`.

## 4. Reload with no restart

```
unbound-control auth_zone_reload rules_kids
```

This rereads one file into the running server. No restart. No cache flush. No
Ansible run. The SOA serial needs no bump.

Verified end to end: a blocked name returned NXDOMAIN, one appended line plus a
reload made it resolve, and removal restored the block at once.

Note the ordering this proves. unbound applies RPZ **before** the cache, so a
removed rule takes effect at once even though the old answer is still cached.
Downstream clients hold their own caches, so a browser lags by its own TTL.
Follow a removal with `unbound-control flush <name>` to be sure.

Other useful commands:

- `unbound-control stats_noreset` reports `num.rpz.action.*` counters, plus
  rcode and query type breakdowns. `extended-statistics` is on. Counters that
  are still zero stay hidden.
- `unbound-control rpz_disable feed_kids` turns off one zone for its whole
  group. `rpz_enable` reverses it. This is the panic button.
- `unbound-control reload_keep_cache` applies a config change without a cache
  flush. The admin runs this after a membership deploy.
- `unbound-control status` and `dump_infra` report health and upstream latency.

## 5. The hosts file

Ansible renders `/etc/dnsrules/hosts.yml` at deploy time, from
`vars/hosts.yml`. dnsrules reads it and never writes it.

YAML, because the source is YAML and the whole `mace` repository is YAML. There
is no JSON reader.

```yaml
groups:
  - name: kids
    zone: rules_kids
    zonefile: /etc/unbound/rules/kids.zone
hosts:
  - name: clove
    addresses: [10.0.0.2, 10.0.0.15, 100.71.4.9]
    groups: [kids]
```

A missing file is an error, not an empty one. Empty renders every zone file
with no rules in it.

It supplies three things:

1. **Where to write.** Each group carries its zone file path and its zone name,
   so dnsrules needs no path convention and no extra setting.
2. **Names for addresses.** The log table shows `clove`, not `10.0.0.2`. Include
   every address of a host, because a host has several interfaces.
3. **Which group applies to which host.** For display only.

The `groups` field on a host is a copy for display. The real membership lives in
the `access-control-tag` lines in `unbound.conf`. dnsrules never reads or writes
those.

Rules for the edge cases:

- **A group leaves `hosts.yml`.** Its rules stay in the database. Mark them
  stale in the UI. Write no file for that group, because there is no path.
- **A host leaves `hosts.yml`.** No rule is affected, because rules belong to
  groups. The address shows as unknown in the log.
- **Dynamic clients.** `systemd-networkd` serves the pool `10.0.1.0/24`. Those
  hosts are absent from `vars/hosts.yml`, so they carry no tag and get no
  blocking. Show them as unmanaged. To manage one, add it to `vars/hosts.yml`.
  Static leases use `10.0.0.0/24`, so the address alone tells you which is which.
- **Tailnet clients.** One `access-control-tag` covers all of `100.64.0.0/10`
  and puts it in one group. Read `tailscale status --json` at runtime for names
  that `hosts.yml` lacks.
- `127.0.0.1` is `mace` itself, through `systemd-resolved`.

## Constraints

- **Never write unbound configuration.** A bad file stops unbound from starting.
- **Never write `/etc/unbound/unbound.conf`.** Ansible owns it. A deploy
  overwrites it.
- **Never write a feed zone file.** unbound owns them and rewrites them about
  every 12 hours. One holds about 430,000 entries, so do not list it in the UI.
  Test single names against it instead.
- **The control socket is `/run/unbound/control.sock`, owned by root, mode
  0755.** A unix socket needs write permission to connect, and unbound never
  chmods it. Only root drives `unbound-control` today.
- **unbound is chrooted to `/etc/unbound`.** This is why the rules directory
  sits under `/etc` and not `/var/lib`. unbound opens a zone file after it
  chroots, so a path outside that tree resolves inside it and the zone fails to
  load. Only `chroot: ""` changes this, and that drops a layer of defence.

  `hosts.yml` carries each zone file path for this reason. If `mace` drops the
  chroot, Ansible changes the paths and dnsrules needs no change.

## Shape

All of `dnsrules` runs on `mace`. Two systemd units share one codebase: the
website, and an ingest service for dnstap and the journal. Both run as
`dnsrules`.

It listens on the LAN address, and you reach it by address and port. This is LAN
first on purpose. It is the tool you want when DNS or the proxy is broken, so
nothing about it depends on either. The tailnet is a secondary path.

`mace` must open the port in `input_allow_rules` in `vars/nftables.yml`, the
same way port 9100 is open for the node exporter.

Do not split the collector from the website across two machines. Every interface
here is local to `mace`: a file, a unix socket, and the journal. Moving the
website off the box turns all three into a network protocol you must design,
secure, and debug.

### Nothing runs as root

Two operations need privilege: write a zone file, and connect to the control
socket. Grant both to a dedicated system user.

1. Add a system user and group, `dnsrules`.
2. Put the rules zone files in `/etc/unbound/rules/`, owned `dnsrules:unbound`,
   mode 0750. Make each file mode 0640. dnsrules writes them, and unbound reads
   them through the group.
3. Add a drop-in for `unbound.service` with an `ExecStartPost` that sets the
   control socket to group `dnsrules`, mode 0770. unbound opens that socket as
   root before it drops privileges, and it never chmods it.
4. Run the service as `dnsrules`, with `SupplementaryGroups=systemd-journal` for
   the journal. Journal access needs a group, not root.

One process is the right start. Note the consequence: anyone who reaches the
website writes RPZ rules, and a rule points any name at any address. This is not
only a blocking control. If that becomes uncomfortable, split the rule writer
into its own unit and keep the boundary clean inside the code. Do not build the
IPC before you want it.

### Authentication

A session cookie, one admin, argon2id password hashing, sessions in the database.

- Never force the `Secure` flag. Plain HTTP on the LAN must keep working,
  because this is the tool you reach for when the proxy is down. Django sets
  `Secure` for each request that already arrived over HTTPS.
- Accept the cost: over plain HTTP the session cookie crosses the LAN in clear
  text. Keep sessions short and bind the listener to the LAN address.
- Keep allowed `Host` and `Origin` values as settings, as lists, and reject
  everything else. With `Secure` gone, this is the main defence, and it stops
  DNS rebinding against the panel.
- `SameSite=Lax` stops the cookie on a cross site POST, which covers form CSRF.

### The database

Postgres holds the rules and the query log. It suits this workload: heavy
append, analytical reads, and time based deletes. `GenericIPAddressField` maps
to `inet`, and `date_trunc` plus `INSERT ... ON CONFLICT` keep the rollups
short. Batch the inserts on a one second tick.

The database runs on `bayleaf`, not on `mace`. The link is Tailscale, so
WireGuard encrypts and authenticates it. That server offers no SSL, so
`sslmode=require` fails there and `sslmode=prefer` falls back to clear text
after a wasted round trip. Use `sslmode=disable`.

DNS never depends on the database. unbound reads the zone files, and those files
stay on disk. Three invariants keep that true:

- **Never render a zone file from an unreachable or empty database.** Reconcile
  only after a successful read. A render at boot with no connection writes an
  empty zone and drops every rule.
- **Take `pg_advisory_xact_lock` around render, write, and reload.** Two workers
  that render at once interleave their writes.
- **Write each file atomically**, as a temporary file and then a rename.

A database outage costs rule changes and expiries, so a temporary allow outlives
its window. Both recover. Neither affects resolution.

### The backup problem

The blocklist URL and the group structure live in git and survive a router
rebuild. The domain rules do not. A rebuild plus a lost database loses your
whole rule set.

So write an export command from the start. `dnsrules export` prints every rule
as YAML, or as JSON with `--format json`. Commit that file. It serves as a
backup and as a record.

## Screens: copy Pi-hole, not its data model

Pi-hole solved this display problem years ago. Take its layout as the
specification.

Worth copying: the query log table with a filter on each column, the client
breakdown, the top blocked and top allowed lists, and the global pause button.

Do not copy its data model. Pi-hole is dnsmasq and has no views. `mace` resolves
`gothere.dev` per client scope and returns NODATA for the Firefox canary on
selected hosts. Any design that puts a filter in front of unbound hides the real
client address and breaks all of it.

The one screen Pi-hole lacks is the one that started this project: a per-domain
allow with an expiry. Design that part with care.

## Retention

Nothing upstream keeps anything for you. journald rotates the RPZ lines, and
dnstap keeps nothing.

Measure before you size anything. Sample the counter one minute apart:

```nu
sudo unbound-control stats_noreset | find total.num.queries
```

Two stores with different lifetimes:

- **Raw rows**, one for each query. The log table filters over these. Keep 30
  days. Partition the table by day, and drop the old partition instead of
  deleting rows. A `DROP` is instant and leaves nothing to vacuum. Index the
  timestamp with BRIN, because the data arrives in time order.
- **Hourly rollups**: client, registrable domain, blocked or not, and a count.
  The graphs read these. Keep 13 months, for a year over year comparison.

Roll up first, then delete the raw rows, each night. Add a size cap as a
backstop, and drop oldest first when it trips. One bad device makes millions of
rows fast.

Expect to lose rows while `bayleaf` is down. The ingest has nowhere to buffer,
and dnstap drops rather than blocks unbound. That is the right way to fail.

## What mace must do

Tracked in that repository under "Work that returns here".

1. **Define the groups.** `define-tag` for each group name, an
   `access-control-tag` for each host address, and two `rpz` blocks for each
   group. Put the rules zone first.
2. **Create `/etc/unbound/rules/`**, owned `dnsrules:unbound`, mode 0750. Create
   each rules zone file once, empty, with `force: false`.
3. **Render `/etc/dnsrules/hosts.yml`** from `vars/hosts.yml` at deploy
   time.
4. **Remove `dont_block` from `vars/unbound_blocklist.yml`**, and remove the
   `privacy_blocklist_overrides` zone. Those entries move into dnsrules as allow
   rules.
5. **Add the `dnsrules` user**, and add the `unbound.service` drop-in for the
   control socket.
6. **Open the website port** in `vars/nftables.yml`.

## Verification recipe

Run on `mace`, as root. This is the control path by hand. `dnsrules` must
reproduce it.

```nu
q google-analytics.com A @127.0.0.1 --format=json | from json | get 0.replies.0.rcode
echo "google-analytics.com CNAME rpz-passthru." | sudo tee --append /etc/unbound/rules/kids.zone
sudo unbound-control auth_zone_reload rules_kids
q google-analytics.com A @127.0.0.1 --format=json | from json | get 0.replies.0.rcode
journalctl --unit unbound --since "-1 min" --output cat | find rules_kids
```

Expect rcode 3, then rcode 0, and one `rpz-passthru` log line. To undo, delete
the line and reload again.

A blocked answer also has the RA bit cleared:

```nu
q google-analytics.com A @127.0.0.1 --format=json | from json | get 0.replies.0 | select rcode recursionavailable
```
