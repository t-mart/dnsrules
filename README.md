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
just dev
just check
```

Every command is a Django management command. `manage.py` is a development
shim. Deployments call the `dnsrules` console script, which is the same entry
point.

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

Two rules that htmx 1 and 2 documentation gets wrong:

- Attribute inheritance is explicit. The CSRF header needs
  `hx-headers:inherited`, not `hx-headers`.
- htmx swaps every response except 204 and 304. `base.html` adds `5xx` to
  `noSwap`, so a server fault does not replace the page.

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

A rule change runs in this order: save the row, render every rule to zone text,
write the file atomically, then reload the zone through the control socket.

| Setting | Purpose |
| --- | --- |
| `DNSRULES_ZONE_PATH` | the zone file dnsrules owns and rewrites |
| `DNSRULES_ZONE_NAME` | the zone to reload |
| `DNSRULES_OVERRIDES_PATH` | Ansible's exemption zone, read only |
| `DNSRULES_CONTROL_SOCKET` | unbound's control socket |

These are settings, not constants, because unbound is chrooted to
`/etc/unbound`. If mace drops the chroot, the zone file moves and one setting
changes.

A development machine has no unbound. Leave `DNSRULES_CONTROL_SOCKET` empty to
write the zone file and skip the reload. Every other reload fault stays an
error. A silent reload failure is the worst outcome here, because the website
reports success while unbound still serves the previous rules.

dnsrules reads the SOA header back out of the zone file rather than keeping its
own copy. Ansible writes that header once, with `force: false`, and never
touches the file again.

## Deployment

Not written yet. The plan: install with
`uv tool install git+https://github.com/t-mart/dnsrules.git` on the router, then
generate the systemd units, the sysusers entry, and the tmpfiles entry from the
installed binary.
