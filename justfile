set dotenv-load := true

default: check

# run the development server. It binds DNSRULES_BIND, because `just unbound`
# fetches the rules across the docker bridge.
dev:
    uv run dnsrules runserver $DNSRULES_BIND

# run the recurring jobs. `serve` does this in a thread; development does not.
worker:
    uv run dnsrules worker

# write the query log from the dnstap stream. `serve` does this in a thread too.
# It listens on every interface, because `just unbound` connects from a
# container. The setting stays on loopback, which is right on the router.
ingest:
    uv run dnsrules ingest --host 0.0.0.0

# run a management command with the development environment loaded
manage *ARGS:
    uv run dnsrules {{ ARGS }}

# start a real unbound to test against. It fetches rules from `just dev` on
# the host, across the docker bridge.
unbound:
    docker build --tag dnsrules-unbound:dev dev
    -docker rm --force dnsrules-unbound
    docker run --detach --name dnsrules-unbound --publish 127.0.0.1:8953:8953 --publish 127.0.0.1:5354:53/udp dnsrules-unbound:dev

# stop it
unbound-stop:
    -docker rm --force dnsrules-unbound

# run the whole thing in containers, the way the router does
up:
    docker compose up --build --detach

# stop that
down:
    docker compose down

# run one control command against it, for example `just control status`
control *ARGS:
    docker exec dnsrules-unbound unbound-control -c /etc/unbound/unbound.conf {{ ARGS }}

# ask it a question, for example `just dig example.com A`
dig *ARGS:
    docker exec dnsrules-unbound dig +noall +comments +answer @127.0.0.1 {{ ARGS }}

# print the answer flags that dnstap carries, one line per query
probe:
    uv run python dev/probe.py

# regenerate the dnstap protobuf module. Needs protoc; the output is committed.
# The stub comes too: protoc builds the classes at import time, so a type
# checker sees nothing without it.
proto:
    protoc --proto_path=assets --python_out=src/dnsrules/unbound --pyi_out=src/dnsrules/unbound assets/dnstap.proto

# run every quality check
check:
    uv run ruff format --check .
    uv run ruff check .
    uv run ty check
    uv run dnsrules check
    uv run dnsrules makemigrations --check --dry-run
    uv run pytest

# apply formatting and lint fixes
fix:
    uv run ruff format .
    uv run ruff check --fix .

# build the wheel and confirm it carries the templates and static files
wheel:
    rm -rf dist
    uv build --wheel
    unzip -l dist/*.whl | grep -E 'templates/|static/'
