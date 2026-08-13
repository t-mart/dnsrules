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
`src/dnsrules/core/static/dnsrules/htmx.min.js`. There is no build step and no
CDN. The panel must work when DNS or the reverse proxy is broken, so it loads
nothing from the network.

The vendored build has this sha384:

```
6lyVbhrs13b9z7mLOpt/N6R76rtkEBWgCjAXRs/DSWyi2AMnQSs10ijWk+PI8n7W
```

Run `just htmx-hash` to compare. An upgrade is a deliberate act: download the
new build, record the new hash here, and read the htmx changelog first.

Two htmx 4 rules that htmx 1 and 2 documentation gets wrong:

- Attribute inheritance is explicit. The CSRF header needs
  `hx-headers:inherited`, not `hx-headers`.
- htmx swaps every response except 204 and 304. `base.html` adds `5xx` to
  `noSwap`, so a server fault does not replace the page.

## Configuration

All settings read `DNSRULES_` environment variables. `.env.example` lists them
with their defaults. `settings.py` must import with an empty environment,
because the install procedure runs commands before the environment file exists.
A test enforces this.

## Deployment

Not written yet. The plan: install with
`uv tool install git+https://github.com/t-mart/dnsrules.git` on the router, then
generate the systemd units, the sysusers entry, and the tmpfiles entry from the
installed binary.
