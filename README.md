# dnsrules

A DNS log and control plane for the home network. It shows every query that
unbound answers, and it blocks or unblocks names from the same page.

See [the TODO](TODO.md) for the design of record and the outstanding work.

## Requirements

- Python 3.14
- PostgreSQL
- [uv](https://docs.astral.sh/uv/)
- [just](https://just.systems/)

## Development

```
cp .env.example .env
just manage migrate
just manage createsuperuser
just dev
just worker
just ingest
just unbound
```

Then open `http://127.0.0.1:8000/rules/` and sign in.

`just dev`, `just worker`, `just ingest`, and `just unbound` run at once, in
their own terminals. `serve` runs the first three in one process, but
development keeps them apart so a traceback lands where you can see it.

Migrations create one group, `home`, which is why the dev resolver fetches
`/rpz/home.zone`. Its `zone` field is what `unbound.conf` calls that zone.

`just unbound` runs a real resolver that fetches its rules from `just dev`. It
reaches the host across the docker bridge, so the server binds `0.0.0.0` and
`DNSRULES_ALLOWED_HOSTS` names the gateway. Both are in `.env.example`.

Every command is a Django management command. `manage.py` is a development shim.
Deployments call the `dnsrules` console script, which is the same entry point.
Run `just manage <command>` in development, because the justfile loads `.env`
and a bare shell does not.

## Configuration

All settings read `DNSRULES_` environment variables. `.env.example` lists them
with their defaults. `settings.py` must import with an empty environment, and a
test enforces this.

## Database

PostgreSQL. Development uses `bayleaf.gothere.dev`, where the database and the
role exist already. The role needs `CREATEDB`, because pytest builds its own
test database:

```
psql --host bayleaf.gothere.dev --username postgres --command "ALTER ROLE dnsrules_test CREATEDB"
```

## unbound

`src/dnsrules/unbound/` holds every part that touches the resolver. It imports
no Django, so it tests without a database.

There are three interfaces, and all of them are TCP to localhost:

| Direction      | Interface      | Carries                      |
| -------------- | -------------- | ---------------------------- |
| Out of unbound | dnstap         | every query and every answer |
| Out of unbound | HTTP           | unbound fetches the rules    |
| Into unbound   | remote control | "fetch the rules again"      |

**dnsrules writes no file that unbound reads, and it never writes unbound
configuration.** A bad configuration file stops unbound from starting, and the
whole house loses DNS.

unbound needs this, and nothing else:

```
rpz:
    name: "runtime_rules"
    url: "http://127.0.0.1:8000/rpz/home.zone"
    zonefile: "/etc/unbound/zones/rpz-runtime-rules.zone"
    tags: "dns_privacy"

remote-control:
    control-enable: yes
    control-interface: 127.0.0.1
    control-use-cert: no
```

The `rpz` block comes before the blocklist, so an allow rule beats a block.
`zonefile` is what makes a dnsrules outage safe: unbound keeps the last fetch
and reloads it at every start.

Plain text control means that anyone who reaches the port drives the resolver.
Bind it to loopback, or to a private container network. Never `0.0.0.0`.

### Rules

Each group has its own zone, served at `/rpz/<group>.zone`. dnsrules renders the
whole thing, SOA included. One rule is one line:

| Action             | Line                          | Answer             |
| ------------------ | ----------------------------- | ------------------ |
| Block              | `<domain> CNAME .`            | NXDOMAIN           |
| Block with no data | `<domain> CNAME *.`           | NOERROR, no answer |
| Allow              | `<domain> CNAME rpz-passthru.` | Resolve, and skip every later zone |

A rule change sets the transfer job due. The worker raises the serial and sends
`auth_zone_transfer runtime_rules` over the control interface, and unbound
refetches at once. RPZ is applied before the cache, so a removed rule takes
effect even while the old answer is still cached.

One process talks to unbound, so a slow or unreachable resolver never holds up a
page. The website reports what the last transfer did and moves on.

The trigger is an optimisation, not the mechanism. A lost trigger costs one SOA
refresh interval, and never correctness.

## Jobs

Three recurring jobs, in one Postgres table. There is no broker and no second
process.

| Job | Every | Does |
| --- | --- | --- |
| `transfer` | 1 hour | Raises the serials and tells unbound |
| `prune` | 1 minute | Deletes expired rules |
| `retention` | 1 day | Deletes query rows past 30 days |

A worker claims the next due row with `FOR UPDATE SKIP LOCKED` and holds that
lock until the job returns, so a second worker takes the next job rather than
the same one. A job that raises is recorded in `last_error` and comes back in
30 seconds, because a worker that dies on one bad job stops every other.

`SCHEDULE` in `core/jobs.py` names each target as a string. The jobs live in the
other apps, and those apps import this one.

`serve` runs the website, the ingest, and the jobs in one process. It takes one
gunicorn worker on purpose: the threads start from `post_worker_init`, after the
fork, so no database connection is ever shared by two processes.

Nothing builds a line from raw input. The domain is validated, and the right
hand side comes from the fixed table above.

### Testing against a real resolver

`just unbound` starts unbound 1.26.0 in a container, with an RPZ feed, a view,
and control on `127.0.0.1:8953`. It fetches its rules from `just dev` on the
host. `dev/` holds its configuration.

```
just unbound
just control status
just dig example.com A
```

Use it to answer questions about the resolver rather than reasoning about them.
The answers that shaped this design are recorded in [the TODO](TODO.md).

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

### What stopped an answer

`blocked_by` holds `rule` or `feed`, and it is stamped at ingest. The two come
from different places, because one answer cannot say both.

A blocked answer carries exactly one usable signal: `rpz-signal-nxdomain-ra:
yes` clears the RA bit on a policy NXDOMAIN. That covers the feed. It cannot
name the zone, and it never sees a `CNAME *.` rule, because NODATA reads exactly
like a legitimate empty answer.

So a rule is read from the rules table instead, which is exact and also names
it. The table is cached for a minute, so a day of rows costs one read.

The AA bit looks like a better signal and is not. unbound sets it for every
local zone, including the LAN names and `.invalid`.

Run `just probe` next to `just unbound` to see the flags for yourself.

Rows live 30 days, in one table, and the retention job deletes the rest.
Measured on one sample, the house makes about 250,000 queries a day, so that is
near 7.5 million rows. Postgres does not notice that many, and `at` carries a
BRIN index because the rows arrive in time order.

## dnstap

`assets/dnstap.proto` is the schema, taken from the dnstap project by way of the
unbound source. `just proto` regenerates `dnstap_pb2.py` and `dnstap_pb2.pyi`
into `src/dnsrules/unbound/`.

Both generated files are committed. `uv tool install git+...` builds a wheel
from the git tree and cannot run protoc. The stub comes too, because protoc
builds the classes at import time and a type checker sees nothing without it.

`protobuf` is the runtime that the generated code imports. `protoc` is the
compiler that writes it. They version together: protoc 35.1 emits code that
demands the 7.35.1 Python runtime or newer.

## Frontend

The frontend is [htmx 4.0.0-beta6](https://four.htmx.org/), vendored at
`src/dnsrules/static/dnsrules/htmx.min.js`. There is no CDN. The panel must work
when DNS or the reverse proxy is broken, so it loads nothing from the network.

The stylesheet at `src/dnsrules/static/dnsrules/app.css` is written by hand, and
there is no build step. Elements carry the styling, and a class appears only
where the markup cannot say what a thing is: a message, a state, or a layout
that has no element. A test fails when a template names a class the stylesheet
does not define.

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

## Fixtures

The dnstap stream uses a format this project does not control. A stream written
here would test the reader against its own assumptions, so one shared misreading
would pass every test and fail on the router. Capture real bytes instead, and
replay them.

`tests/fixtures/dnstap.fstrm` holds a capture. **It is never committed.** It
records every DNS query the house made during its window, which is a browsing
history. `.gitignore` lists it, and every test that needs it skips when it is
absent. `pytest` runs with `-rs`, so a skip always prints its reason.

`.fstrm` is Frame Streams, the envelope around each message: a 4 byte big-endian
length, then the payload. A zero length escapes to a control frame. Each data
frame payload is a protobuf `dnstap.Dnstap` message.

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

Run it for about ten seconds, then stop it with Ctrl-C. unbound connects out, so
nothing needs to be installed and no port needs to open.

```nu
python3 /tmp/capture.py /tmp/dnstap.fstrm 6000
strings /tmp/dnstap.fstrm | uniq | first 50
scp mace:/tmp/dnstap.fstrm tests/fixtures/dnstap.fstrm
```

Read it with `strings` before it leaves the router. Delete it and capture again
at a quieter moment if it holds anything you would rather not keep.
