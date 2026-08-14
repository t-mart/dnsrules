# dnsrules

A DNS log and block dashboard for
[Unbound](https://github.com/NLnetLabs/unbound). Similar to the DNS management
sides of Pi-hole and AdGuard Home.

- A dashboard counts the traffic over a window from 15 minutes to a week.
- A query log lists every question a client asked, with the answer and the reply
  time. Filter by client, name, record type, status, and time.
- A rules page lists block rules (or allow) rules. Add, edit, and delete them
  here, and Unbound will update with them.

## Rules

A rule is a domain and an action. Wildcards are accepted, as `*.example.com`.

| Action               | Answer             | Use it for                            |
| -------------------- | ------------------ | ------------------------------------- |
| Block                | NXDOMAIN           | a name you do not want resolved       |
| Block, answer NODATA | NOERROR, no answer | a name that must exist but stay empty |
| Allow                | the real answer    | a false positive in the blocklist     |

In most cases, you will write NXDOMAIN rules to block a name. This indicates to
applications that the name does not exist.

A NODATA rule is useful when you want an application to see that a name exists,
but you do not want there to be any records served on it. (I actually don't even
know what I'd want that, but whatever.) Note: A NODATA rule does not reach the
log. TODO: should we delete the NODATA option?

Allow rules are helpful to override later RPZ zones that block it. For example,
you might configure a client to use a blocklist, but you need to reach a site
that it blocks. In this case, you can override it with an allow rule for that
domain that will take precedence.

A rule is permanent, or it expires after 15 minutes, an hour, 8 hours, a day, or
a week.

## How it works

To get query log information, dnsrules consumes Unbound's dnstap stream and
writes it to PostgreSQL. The web interface reads the log from the database.

This makes it easy to see which rules are being applied to which clients.

dnsrules renders the rules as an RPZ zone and serves it over HTTP. Then, Unbound
can consume it just like any other in its config. To prompt Unbound to refetch
the rules when you change them, dnsrules uses Unbound's remote control.

When configured, Unbound does not depend on dnsrules. This is important: if
dnsrules encounters a problem, Unbound will still work. (However, the rules may
be stale until the problem is fixed.)

## Requirements

- Unbound, with RPZ, remote control, and dnstap enabled. See
  [Configure Unbound](#configure-unbound).
- PostgreSQL, on this host or another one. It holds the rules and the query log.
- Python 3.14 and [uv](https://docs.astral.sh/uv/).
- [just](https://just.systems/), for development.

## Setup

```
uv tool install git+https://github.com/t-mart/dnsrules
dnsrules secret  # print a key for the environment file
dnsrules serve  # run the website
dnsrules createsuperuser  # create the first account
```

`serve` runs the website, the query log, and the jobs in one process. It applies
the database migrations first, so an upgrade is an install and a restart.

### Systemd

Install to a fixed path, so the unit can name it:

```
sudo env UV_TOOL_BIN_DIR=/usr/local/bin UV_TOOL_DIR=/opt/dnsrules \
    uv tool install git+https://github.com/t-mart/dnsrules
```

Put the settings in `/etc/dnsrules.env`, then write
`/etc/systemd/system/dnsrules.service`:

```ini
[Unit]
Description=dnsrules
After=network-online.target
Wants=network-online.target

[Service]
User=dnsrules
EnvironmentFile=/etc/dnsrules.env
ExecStart=/usr/local/bin/dnsrules serve
Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
```

```
sudo systemctl enable --now dnsrules
```

`Restart=always` covers a database that is not up yet. There is no dependency on
`unbound.service` in either direction: Unbound falls back to its `zonefile`, and
dnsrules records a failed transfer and tries again.

### Docker Compose

dnsrules has to reach Unbound's control port and receive the dnstap stream, and
both are on loopback. Host networking is the simplest way to keep that true.

```yaml
services:
  dnsrules:
    build: https://github.com/t-mart/dnsrules.git
    network_mode: host # so 127.0.0.1 is the host, where Unbound runs
    env_file: .env # set DNSRULES_BIND, or it answers on every interface
    restart: unless-stopped

  db:
    image: postgres:17
    environment:
      POSTGRES_DB: dnsrules
      POSTGRES_USER: dnsrules
      POSTGRES_PASSWORD: ${DNSRULES_DB_PASSWORD}
    ports:
      - "127.0.0.1:5432:5432" # host networking reaches it here
    volumes:
      - db:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  db:
```

```
docker compose up --detach
docker compose exec dnsrules dnsrules createsuperuser
```

Run Unbound in a container too, and neither side can use loopback or a host
name: `dnstap-ip` takes no host name, and a resolver cannot use DNS to find the
thing that configures it. Give each container a fixed address on a private
network. [compose.yaml](compose.yaml) does this for development.

## Configuration

Every setting is a `DNSRULES_` environment variable.
[.env.example](.env.example) lists them all with their defaults.

| Variable                       | Sets                                         |
| ------------------------------ | -------------------------------------------- |
| `SECRET_KEY`                   | Signs the session cookies.                   |
| `BIND`                         | The address and port the website answers on. |
| `ALLOWED_HOSTS`                | The host names the site accepts.             |
| `CSRF_TRUSTED_ORIGINS`         | Extra origins, for a reverse proxy.          |
| `TIME_ZONE`                    | The zone the site prints times in.           |
| `DB_NAME`, `DB_USER`, `DB_...` | The PostgreSQL connection.                   |
| `DNSTAP_HOST`, `DNSTAP_PORT`   | Where Unbound sends the query stream.        |
| `CONTROL_HOST`, `CONTROL_PORT` | Unbound's remote control.                    |
| `RPZ_ZONES`                    | The rules zones, comma separated.            |
| `DEBUG`                        | Django debug mode.                           |

## Configure Unbound

Example `unbound.conf`. Tailor to your needs.

```
server:
    # respip is required for RPZ. define-tag must come before any use of a tag.
    module-config: "respip validator iterator"
    define-tag: "filtered"

    # An RPZ zone applies to a client only through a tag it carries.
    access-control: 10.0.0.0/24 allow
    access-control-tag: 10.0.0.0/24 "filtered"

# The dnsrules zone comes first, so an allow rule here beats a block below.
# One clause for each name in `RPZ_ZONES`.
rpz:
    name: "dnsrules"
    url: "http://127.0.0.1:8000/rpz/dnsrules.zone"
    zonefile: "/var/lib/unbound/rpz-dnsrules.zone"
    tags: "filtered"
    rpz-signal-nxdomain-ra: yes

# Your blocklist, for example one of https://github.com/hagezi/dns-blocklists
rpz:
    name: "blocklist"
    url: "https://cdn.jsdelivr.net/gh/hagezi/dns-blocklists@latest/rpz/pro.txt"
    zonefile: "/var/lib/unbound/rpz-blocklist.zone"
    tags: "filtered"
    rpz-signal-nxdomain-ra: yes

remote-control:
    control-enable: yes
    control-interface: 127.0.0.1
    control-use-cert: no

dnstap:
    dnstap-enable: yes
    dnstap-ip: "127.0.0.1@6000"
    dnstap-bidirectional: no
    dnstap-log-client-query-messages: yes
    dnstap-log-client-response-messages: yes
```

Order matters. Unbound reads RPZ zones in the order they appear, and the first
match wins, so the dnsrules zone must come before any blocklist it overrides.

Keep `zonefile` on both. It holds the last fetch, so Unbound reloads the rules
at every start, and a dnsrules outage never unblocks the network.

`rpz-signal-nxdomain-ra` clears the RA bit on a blocked answer. Without it, the
query log cannot tell a blocked name from a name that does not exist.

### More than one zone

Set `DNSRULES_RPZ_ZONES=dnsrules,kids` and write an `rpz` clause for each name.
Give each clause its own tag, and tag the clients that zone must reach:

```
    define-tag: "filtered kids"
    access-control-tag: 10.0.0.30/32 "filtered kids"
```

Then a rule in the `kids` zone reaches those clients alone. dnsrules serves each
zone at its own URL, transfers each one, and the rules page gives each its own
section. From the query log, "Every zone" writes the rule to all of them.

Unbound decides who a zone reaches, and it reports that to nothing. Keep the
tags in `unbound.conf` and the names in `RPZ_ZONES` in step by hand.

It may be ideal to keep `dnstap-ip` and `control-interface` on `127.0.0.1`. The
dnstap stream exposes browsing history, and remote control has no password, so
whoever reaches that port can drive the resolver.

## Jobs

Three jobs run in the background.

| Job         | Every    | Does                             |
| ----------- | -------- | -------------------------------- |
| `transfer`  | 1 hour   | Tells Unbound to fetch the rules |
| `prune`     | 1 minute | Deletes expired rules            |
| `retention` | 1 day    | Deletes query rows past 30 days  |

A rule change makes the transfer job due at once, so the hourly run is just a
safety net. A job that fails is recorded and runs again in 30 seconds, and the
rules page reports the last failure.

## Development

```
cp .env.example .env
just manage migrate
just manage createsuperuser
just dev
```

Then open `http://127.0.0.1:8000/` and sign in.

Run `just dev`, `just worker`, `just ingest`, and `just unbound` at once, in
four terminals. `serve` runs the first three in one process, but development
keeps them apart so a traceback lands where you can see it.

| Recipe                 | Does                                          |
| ---------------------- | --------------------------------------------- |
| `just dev`             | Run the development server                    |
| `just worker`          | Run the recurring jobs                        |
| `just ingest`          | Write the query log                           |
| `just unbound`         | Start a real resolver to test against         |
| `just unbound-stop`    | Stop it                                       |
| `just control ARGS`    | Run one `unbound-control` command against it  |
| `just dig ARGS`        | Ask it a question                             |
| `just probe`           | Print the answer flags for each kind of block |
| `just up`, `just down` | Run both halves in containers                 |
| `just manage ARGS`     | Run a management command                      |
| `just check`           | Run every format, lint, type, and test check  |
| `just fix`             | Apply format and lint fixes                   |
| `just proto`           | Regenerate the dnstap module                  |
| `just wheel`           | Build the wheel and list its assets           |

`just up` runs both halves in containers. It is a test tool. The deployment
installs the package and runs it under systemd.

Read [DEVELOPMENT.md](DEVELOPMENT.md) before a change to the frontend, the
dnstap reader, or the test fixtures.

## Documents

| Document                         | Holds                                                                           |
| -------------------------------- | ------------------------------------------------------------------------------- |
| [TODO.md](TODO.md)               | The design of record, the measured resolver behaviour, and the outstanding work |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Notes for a change to this code                                                 |
