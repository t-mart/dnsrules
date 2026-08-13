# dnsrules

A DNS log and control plane for the home network. It shows every resolution
that unbound performs, and it blocks or unblocks names from the same page.

`dnsrules` names the project, the system user it runs as, and the group that
reaches unbound. See [the handoff](dns-visibility-handoff.md) for the
interfaces it uses on the router.

## Requirements

- Python 3.14
- PostgreSQL
- [uv](https://docs.astral.sh/uv/)
- [just](https://just.systems/)

## Development

```
cp .env.example .env
just hosts
just manage migrate
just manage createsuperuser
just dev
```

Then open `http://127.0.0.1:8000/rules/` and sign in.

Every command is a Django management command. `manage.py` is a development
shim. Deployments call the `dnsrules` console script, which is the same entry
point. Run `just manage <command>` in development, because the justfile loads
`.env` and a bare shell does not.

## Frontend

The frontend is [htmx 4.0.0-beta6](https://four.htmx.org/), vendored at
`src/dnsrules/static/dnsrules/htmx.min.js`. There is no CDN. The panel must work
when DNS or the reverse proxy is broken, so it loads nothing from the network.

The vendored build has this sha384:

```
6lyVbhrs13b9z7mLOpt/N6R76rtkEBWgCjAXRs/DSWyi2AMnQSs10ijWk+PI8n7W
```

Run `just htmx-hash` to compare. An upgrade is a deliberate act: download the
new build, record the new hash here, and read the htmx changelog first.

## Styling

Tailwind CSS 4, built by
[django-tailwind-cli](https://django-tailwind-cli.readthedocs.io/). It downloads
the standalone Tailwind binary, so the project needs no Node.js.

| Path | Role |
| --- | --- |
| `assets/app.css` | source, outside the package so it is never served |
| `src/dnsrules/static/dnsrules/app.css` | compiled output, committed |
| `.django_tailwind_cli/` | the downloaded binary, ignored by git |

The compiled stylesheet is committed on purpose. `uv tool install git+...`
builds a wheel from the git tree and cannot run a CSS compiler, so any file that
git does not track cannot reach the router.

The risk is a stale stylesheet: edit a template, forget to rebuild, and the new
classes do nothing. `just check` rebuilds and then fails if the committed file
changed, so the mistake cannot survive a check.

Run `just dev` during development. It serves the site and rebuilds the
stylesheet on every change.

## htmx 4

Four rules that htmx 1 and 2 documentation gets wrong. Read
[the htmx 4 docs](https://four.htmx.org/llms-full.txt), never an older guide.

- Attribute inheritance is explicit, and it reaches descendants only. The CSRF
  header needs `hx-headers:inherited`, not `hx-headers`. The rules panel
  declares `hx-target:inherited` and `hx-swap:inherited` once on its root.
- The default swap is `innerHTML`. Every control that replaces the panel states
  `outerHTML`, otherwise the panel nests inside itself.
- htmx swaps every response except 204 and 304. `base.html` adds `5xx` to
  `noSwap`, so a server fault does not replace the page. A 4xx still swaps, so
  an invalid form answers 422 with its own errors.
- `hx-confirm` is no longer part of the core.

## Configuration

All settings read `DNSRULES_` environment variables. `.env.example` lists them
with their defaults. `settings.py` must import with an empty environment,
because the install procedure runs commands before the environment file exists.
A test enforces this.

## Database

PostgreSQL. Development uses `bayleaf.gothere.dev`, where the database and the
role exist already. The role needs `CREATEDB`, because pytest builds its own
test database:

```
psql --host bayleaf.gothere.dev --username postgres --command "ALTER ROLE dnsrules_test CREATEDB"
```

`DNSRULES_DB_SSLMODE=disable` is correct for that server. It offers no SSL, so
`require` fails and `prefer` falls back to plain text after a wasted round trip.
The link is Tailscale, which encrypts and authenticates it already.

On mace, dnsrules keeps its rules in Postgres on a different host. A database
outage stops rule changes, and it stops expiries, so a temporary unblock
outlives its window. Resolution continues, because unbound reads the zone file
from disk.

## unbound

`src/dnsrules/unbound/` holds every part that touches the router. It imports no
Django, so it tests without a database.

A rule change runs in this order: save the row, render each group's rules to
zone text, write each file atomically, then reload each zone through the control
socket.

**dnsrules writes zone files. It never writes unbound configuration.** A bad
zone file makes unbound skip one zone. A bad configuration file stops unbound
from starting, and the whole house loses DNS.

| Setting | Purpose |
| --- | --- |
| `DNSRULES_HOSTS_PATH` | the file Ansible renders, read only |
| `DNSRULES_ZONE_MODE` | mode for each zone file dnsrules writes |
| `DNSRULES_CONTROL_SOCKET` | unbound's control socket |

A development machine has no unbound. Leave `DNSRULES_CONTROL_SOCKET` empty to
write the zone files and skip the reload. Every other reload fault stays an
error. A silent reload failure is the worst outcome here, because the website
reports success while unbound still serves the previous rules.

dnsrules reads the SOA header back out of each zone file rather than keeping its
own copy. Ansible writes that header once, with `force: false`, and never
touches the file again.

## The hosts file

Ansible owns host names, addresses, group names, and membership. It renders
`/etc/dnsrules/hosts.yml` at deploy time from `vars/hosts.yml`. dnsrules
reads that file and never writes it.

```yaml
groups:
  - name: kids
    zone: rules_kids
    zonefile: /etc/unbound/rules/kids.zone
hosts:
  - name: clove
    addresses: [10.0.0.2, 100.71.4.9]
    groups: [kids]
networks:
  - name: lan
    cidr: 10.0.0.0/24
  - name: dhcp pool
    cidr: 10.0.1.0/24
    managed: false
  - name: tailnet
    cidr: 100.64.0.0/10
```

The networks name each client's home and say whether any policy reaches it. A
client in the DHCP pool is absent from `vars/hosts.yml`, so it carries no tag in
`unbound.conf` and no rule reaches it. The log marks it unmanaged rather than
leaving you to wonder.

Each group carries its own zone name and zone file path, so no setting names a
zone file. unbound is chrooted to `/etc/unbound`, which is why the rules live
under `/etc`. If mace drops the chroot, Ansible changes the paths and dnsrules
needs no change.

A missing file is an error, not an empty one. Empty would render every zone
file with no rules in it.

A group that leaves the file keeps its rules and its row. Nothing renders
for it, because nothing says where to write. The rules page marks it stale.
Membership changes need an Ansible deploy and then
`unbound-control reload_keep_cache`.

Run `just hosts` to write a stand-in into `var/` for development.

Three commands drive the zone files:

```
uv run dnsrules reconcile
uv run dnsrules prune
uv run dnsrules export | save --force rules.yml
```

`reconcile` renders every active rule and reloads. `prune` deletes expired
rules first, and does nothing more when none expired. `export` prints every
rule as YAML, or as JSON with `--format json`. The group structure lives in the
mace repository and survives a rebuild. The rules live only in Postgres, so
commit that export as the backup.

## dnstap

`assets/dnstap.proto` is the schema, taken from the dnstap project by way of the
unbound source. `just proto` regenerates `dnstap_pb2.py` and `dnstap_pb2.pyi`
into `src/dnsrules/unbound/`.

Both generated files are committed, for the same reason the stylesheet is:
`uv tool install git+...` builds a wheel from the git tree and cannot run
protoc. The stub comes too, because protoc builds the classes at import time and
a type checker sees nothing without it.

`protobuf` is the runtime the generated code imports. `protoc` is the compiler
that writes it. They version together: protoc 35.1 emits code that demands the
7.35.1 Python runtime or newer.

## The query log

`dnsrules ingest` listens for the dnstap stream and writes one row for each
question a client asked. unbound is the client on that socket: it connects out
to `DNSRULES_DNSTAP_HOST` and `DNSRULES_DNSTAP_PORT`, and it reconnects about
once a second while nothing listens.

The pipeline is a chain of generators, so memory holds one batch and the queries
still waiting for an answer:

```
bytes -> frames -> records -> exchanges -> rows
```

A query and its answer arrive as two dnstap messages. unbound stamps the answer
with `response_time` and never with `query_time`, so reply time exists only
across the pair. The key is client, port, name, and type, and it repeats,
because clients reuse a source port. Each key holds a queue, and the oldest
query takes the next answer.

`/queries/` shows the rows, with a filter on each column and a control on each
row. Block or allow a name from the row that shows it, for an hour or for good.
A second click replaces the first rule rather than adding a second one.

The table is partitioned by day. Measured on one sample, the house makes about
250,000 queries a day, so 30 days is near 7.5 million rows. Dropping a partition
is instant and leaves nothing to vacuum.

```
uv run dnsrules partitions --ahead 7 --keep 30
```

Run it daily, and well ahead of the rows it serves. A day with no partition
still accepts rows, into the DEFAULT partition, and that day can then no longer
take a partition of its own. The command reports it when that happens.

`DNSRULES_LOG_MAX_BYTES` is a backstop under that retention, not a schedule.
The oldest day goes early when the log passes it. The command says so, and it
never drops today or a day that is still coming.

## The archive

Raw rows live 30 days. `dnsrules rollup` keeps a small archive for 13 months,
in two shapes:

| Table | Holds | Rows a day |
| --- | --- | --- |
| `queries_hour` | One hour of one client, blocked or not, and a count | near 600 |
| `queries_top` | The 100 leading names of a day, blocked and allowed apart | 200 |

The name is the whole cost of an archive. Measured on a real capture, an hourly
rollup keyed on the name holds near 1,600 rows an hour. That is 15 million rows
over 13 months, against the 7.5 million raw rows it replaces. An archive that
costs twice the thing it archives is not one.

Folding names to the registrable domain only halves that, and it needs the
public suffix list to be correct: two labels turn `bbc.co.uk` into `co.uk`. So
the archive drops the name where it costs the most, and keeps a head of it
where a reader wants one. In one capture of 608 queries, 162 names appeared,
and the top 50 covered 64 percent of them.

Rollups run over finished hours and finished days. The hour that is still
filling waits, because a count that changes after it is written is worse than
one that arrives late. Every statement is an upsert, so a second run writes the
same numbers.

The nightly unit runs `rollup`, then `partitions`. A oneshot stops at the first
failure, so a rollup that fails keeps the day it had not read yet.

## Fixtures

The dnstap stream and the RPZ log lines use formats this project does not
control. A stream written here would test the reader against its own
assumptions, so one shared misreading would pass every test and fail on the
router. Capture real bytes instead, and replay them.

`tests/fixtures/dnstap.fstrm` holds a capture. **It is never committed.** It
records every DNS query the house made during its window, which is a browsing
history. `.gitignore` lists it, and every test that needs it skips when it is
absent. `pytest` runs with `-rs`, so a skip always prints its reason.

`.fstrm` is Frame Streams, the envelope around each message: a 4 byte
big-endian length, then the payload. A zero length escapes to a control frame.
Each data frame payload is a protobuf `dnstap.Dnstap` message.

To capture one, write this listener on the router:

```nu
'import socket
import sys

path, port = sys.argv[1], int(sys.argv[2])
listener = socket.create_server(("127.0.0.1", port))
print(f"Listening on 127.0.0.1:{port}. Stop with Ctrl-C.")
connection, peer = listener.accept()
total = 0
try:
    with open(path, "wb") as out:
        while chunk := connection.recv(65536):
            out.write(chunk)
            total += len(chunk)
finally:
    print(f"Wrote {total} bytes to {path}.")
' | save --force /tmp/capture.py
```

Run it for about ten seconds, then stop it with Ctrl-C. unbound connects out,
so nothing needs to be installed and no port needs to open.

```nu
python3 /tmp/capture.py /tmp/dnstap.fstrm 6000
strings /tmp/dnstap.fstrm | uniq | first 50
scp mace:/tmp/dnstap.fstrm tests/fixtures/dnstap.fstrm
```

Read it with `strings` before it leaves the router. Delete it and capture again
at a quieter moment if it holds anything you would rather not keep.

## Deployment

The router is `mace`. Ansible owns unbound and the hosts file. dnsrules
installs on top with `uv tool install`, and it brings its own units.

`src/dnsrules/units/` holds them as real files, and that tree mirrors `/etc`.
The `units` command copies them, and it renders nothing: no unit depends on
runtime state. Every path inside a unit is fixed by convention. To change one
on a router, write a drop-in with `systemctl edit`. A drop-in survives the next
upgrade, and an edited unit does not.

### Install

1. Install the tool where a service user can reach it.

   ```
   sudo env UV_TOOL_DIR=/usr/local/lib/uv UV_TOOL_BIN_DIR=/usr/local/bin uv tool install git+https://github.com/t-mart/dnsrules.git
   ```

   Both variables are necessary. Without them the environment lands under
   `/root`, which the `dnsrules` user cannot read.

2. Put the units in place. Run `dnsrules units` alone first, to see the list.

   ```
   sudo dnsrules units --output /etc
   sudo systemd-sysusers
   sudo systemd-tmpfiles --create
   sudo systemctl daemon-reload
   ```

3. Make the environment file. `.env.example` describes every variable.

   ```
   sudo touch /etc/dnsrules/dnsrules.env
   sudo chown root:dnsrules /etc/dnsrules/dnsrules.env
   sudo chmod 640 /etc/dnsrules/dnsrules.env
   dnsrules secret | sudo tee --append /etc/dnsrules/dnsrules.env
   sudoedit /etc/dnsrules/dnsrules.env
   ```

   The file holds the database password and the secret key, so it stays at
   `640`. `dnsrules secret` prints a line and writes no file, so it cannot
   replace a key that sessions depend on.

4. Restart unbound. The drop-in gives the control socket to the unbound group,
   and the `dnsrules` user is a member.

   ```
   sudo systemctl restart unbound
   ```

5. Start the services.

   ```
   sudo systemctl enable --now dnsrules-web dnsrules-ingest
   sudo systemctl enable --now dnsrules-prune.timer dnsrules-nightly.timer
   ```

6. Make the first account.

   ```
   sudo systemd-run --pty --uid=dnsrules --property=EnvironmentFile=/etc/dnsrules/dnsrules.env /usr/local/bin/dnsrules createsuperuser
   ```

   `systemd-run` gives the command the same environment as the units. `sudo
   --user` gives it none, so it finds no database.

### Upgrade

```
sudo env UV_TOOL_DIR=/usr/local/lib/uv UV_TOOL_BIN_DIR=/usr/local/bin uv tool upgrade dnsrules
sudo dnsrules units --output /etc --force
sudo systemctl daemon-reload
sudo systemctl restart dnsrules-migrate dnsrules-web dnsrules-ingest
```

`dnsrules-migrate` is a oneshot with `RemainAfterExit=yes`, so a restart runs
the migrations again. The other units order themselves after it, and systemd
holds that order inside one restart.

### The units

| Unit | Does |
| --- | --- |
| `dnsrules-migrate.service` | Applies migrations. Every other unit waits for it |
| `dnsrules-web.service` | Serves the website through gunicorn |
| `dnsrules-ingest.service` | Writes the query log from the dnstap stream |
| `dnsrules-prune.timer` | Deletes expired rules every minute |
| `dnsrules-nightly.timer` | Rolls the log up, then moves its partitions on |

`dnsrules-web` and `dnsrules-prune` write a zone file and reload a zone. They
carry `ProtectSystem=strict`, which makes `/etc` read-only, so both list
`/etc/unbound/rules` in `ReadWritePaths`. The others touch the database alone.
