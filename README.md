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
```

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

Not written yet. The plan: install with
`uv tool install git+https://github.com/t-mart/dnsrules.git` on the router, then
generate the systemd units, the sysusers entry, and the tmpfiles entry from the
installed binary.
