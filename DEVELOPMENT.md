# Development

Notes for a change to this code. Read [README.md](README.md) first for what the
project does, and [TODO.md](TODO.md) for the design of record.

## Checks

```
just check
just fix
```

`just check` runs the formatter, the linter, the type checker, the Django system
check, a migration check, and the tests. Run it before a commit.

## Layout

Every command is a Django management command. `manage.py` is a development shim,
and a deployment calls the `dnsrules` console script. Both are the same entry
point. Run `just manage <command>` in development, because the justfile loads
`.env` and a bare shell does not.

`src/dnsrules/unbound/` holds every part that touches the resolver. It imports
no Django, so it tests without a database.

## Database

`.env` names the server. The role needs `CREATEDB`, because pytest builds its own
test database:

```
psql --username postgres --command "ALTER ROLE dnsrules_test CREATEDB"
```

Migrations create the rules zone from `DNSRULES_RPZ_NAME` and
`DNSRULES_RPZ_ZONE`, which both default to `dnsrules`. That is why the
development resolver fetches `/rpz/dnsrules.zone`. The settings seed the row and
nothing more, so a rename on an existing database is a change to the row.

## Test against a real resolver

`just unbound` starts Unbound 1.26.0 in a container, with an RPZ feed, a view,
and control on `127.0.0.1:8953`. It fetches its rules from `just dev` on the
host, across the docker bridge, so the server binds `0.0.0.0` and
`DNSRULES_ALLOWED_HOSTS` names the gateway. Both are in `.env.example`.
`dev/` holds the resolver configuration.

```
just unbound
just control status
just dig example.com A
just probe
```

Use it to answer a question about the resolver rather than to reason about it.
The answers that shaped this design are in [TODO.md](TODO.md), each with the
version it was measured against. Measure again after an upgrade.

`just probe` prints the answer flags for each kind of block. It is how the query
log learned that a cleared RA bit is the only usable in-band signal, and that AA
is not.

## Containers

```
just up
just down
```

`compose.yaml` runs one dnsrules container and one Unbound container on a private
network. This is a test tool, not the deployment.

The addresses in `compose.yaml` are fixed on purpose. `dnstap-ip` takes no
hostname, and a resolver cannot use DNS to find the thing that configures it.
`dev/entrypoint.sh` substitutes that one address at start, so the same Unbound
image serves `just unbound` and the compose stack.

A container cannot reach the host resolver at `127.0.0.53`, and the database
answers to a tailnet name. `COMPOSE_DNS` names the resolver to use instead, and
it defaults to tailscale MagicDNS.

`just unbound` and `compose.yaml` share the container name `dnsrules-unbound`, so
that `just control` and `just dig` reach either one. The cost is that
`just unbound` removes a running compose container. Do not run both.

## Frontend

The frontend is [htmx 4.0.0-beta6](https://four.htmx.org/), vendored at
`src/dnsrules/static/dnsrules/htmx.min.js`. There is no CDN. The panel must work
when DNS or the reverse proxy is broken, so it loads nothing from the network.

Four rules that htmx 1 and 2 documentation gets wrong. Read
[the htmx 4 docs](https://four.htmx.org/llms-full.txt), never an older guide.

- Attribute inheritance is explicit, and it reaches descendants only. The CSRF
  header needs `hx-headers:inherited`, not `hx-headers`. The rules panel declares
  `hx-target:inherited` and `hx-swap:inherited` once on its root.
- The default swap is `innerHTML`. Every control that replaces the panel states
  `outerHTML`, otherwise the panel nests inside itself.
- htmx swaps every response except 204 and 304. `base.html` adds `5xx` to
  `noSwap`, so a server fault does not replace the page. A 4xx still swaps, so an
  invalid form answers 422 with its own errors.
- `hx-confirm` is no longer part of the core.

The stylesheet at `src/dnsrules/static/dnsrules/app.css` is written by hand, and
there is no build step. Elements carry the styling, and a class appears only
where the markup cannot say what a thing is: a message, a state, or a layout that
has no element. A test fails when a template names a class the stylesheet does
not define.

The dashboard timeline is Chart.js from a CDN, pinned to its hash, on that page
alone. Take the UMD build, `chart.umd.min.js`. The `chart.min.js` that cdnjs
offers first is an ES module, and a plain script tag stops on its first import
statement.

htmx replaces the whole dashboard panel, canvas included. `charts.js` draws the
new chart from `htmx:after:process` and destroys the old one, because Chart.js
holds the canvas it drew into until it is told otherwise. htmx processes the
document as soon as it runs, which is before a later deferred script runs, so the
first chart is drawn by a direct call and not by that callback.

A quiet bucket has no row in the database. The empty buckets are made in Python,
because a chart that skipped them would draw a silent hour as if it never
happened.

## dnstap

`assets/dnstap.proto` is the schema, taken from the dnstap project by way of the
Unbound source. `just proto` regenerates `dnstap_pb2.py` and `dnstap_pb2.pyi`
into `src/dnsrules/unbound/`.

Both generated files are committed. `uv tool install git+...` builds a wheel from
the git tree and cannot run protoc. The stub comes too, because protoc builds the
classes at import time and a type checker sees nothing without it.

`protobuf` is the runtime that the generated code imports. `protoc` is the
compiler that writes it. They version together: protoc 35.1 emits code that
demands the 7.35.1 Python runtime or newer.

A query and its answer arrive as two dnstap messages. Unbound stamps the answer
with `response_time` and never with `query_time`, so a reply time exists only
across the pair. The key is client, port, name, and type, and it repeats, because
a client reuses a source port. Each key holds a queue, and the oldest query takes
the next answer.

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

Run it for about ten seconds, then stop it with Ctrl-C. Unbound connects out, so
nothing needs an install and no port needs to open.

```nu
python3 /tmp/capture.py /tmp/dnstap.fstrm 6000
strings /tmp/dnstap.fstrm | uniq | first 50
scp <host>:/tmp/dnstap.fstrm tests/fixtures/dnstap.fstrm
```

Read it with `strings` before it leaves the resolver. Delete it and capture again
at a quieter moment if it holds anything you would rather not keep.
