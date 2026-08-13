set dotenv-load := true

default: check

# run the development server, rebuilding css on every change
dev: var
    uv run dnsrules tailwind runserver

# run a management command with the development environment loaded
manage *ARGS:
    uv run dnsrules {{ ARGS }}

# start a real unbound to test against. It fetches rules from `just dev`.
unbound:
    docker build --tag dnsrules-unbound:dev dev
    -docker rm --force dnsrules-unbound
    docker run --detach --name dnsrules-unbound --publish 127.0.0.1:8953:8953 --publish 127.0.0.1:5354:53/udp dnsrules-unbound:dev

# stop it
unbound-stop:
    -docker rm --force dnsrules-unbound

# run one control command against it, for example `just control status`
control *ARGS:
    docker exec dnsrules-unbound unbound-control -c /etc/unbound/unbound.conf {{ ARGS }}

# ask it a question, for example `just dig example.com A`
dig *ARGS:
    docker exec dnsrules-unbound dig +noall +comments +answer @127.0.0.1 {{ ARGS }}

# stand in for the router's /etc/unbound, which no development machine has
var:
    mkdir --parents var

# write a stand-in for the hosts file that Ansible renders on the router
hosts: var
    #!/usr/bin/env bash
    set -euo pipefail
    cat > var/hosts.yml <<EOF
    groups:
      - name: home
        zone: rules_home
        zonefile: $PWD/var/home.zone
      - name: kids
        zone: rules_kids
        zonefile: $PWD/var/kids.zone
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
    EOF
    echo "Wrote var/hosts.yml."

# regenerate the dnstap protobuf module. Needs protoc; the output is committed.
# The stub comes too: protoc builds the classes at import time, so a type
# checker sees nothing without it.
proto:
    protoc --proto_path=assets --python_out=src/dnsrules/unbound --pyi_out=src/dnsrules/unbound assets/dnstap.proto

# compile the stylesheet
# --force is required: the up-to-date check reads the source css only, so a
# template edit alone never triggers a rebuild.
css:
    uv run dnsrules tailwind build --force

# recompile the stylesheet on every change
css-watch:
    uv run dnsrules tailwind watch

# fail if the committed stylesheet does not match a fresh build
css-check:
    #!/usr/bin/env bash
    set -euo pipefail
    dist=src/dnsrules/static/dnsrules/app.css
    before=$(sha256sum "$dist" | cut --delimiter=' ' --fields=1)
    just css
    after=$(sha256sum "$dist" | cut --delimiter=' ' --fields=1)
    if [ "$before" != "$after" ]; then
        echo "$dist was stale and has been rebuilt. Commit it." >&2
        exit 1
    fi

# run every quality check
check:
    uv run ruff format --check .
    uv run ruff check .
    uv run ty check
    just css-check
    uv run dnsrules check
    uv run dnsrules makemigrations --check --dry-run
    uv run pytest

# apply formatting and lint fixes
fix:
    uv run ruff format .
    uv run ruff check --fix .

# build the wheel and confirm it carries the templates, static files, and units
wheel:
    rm -rf dist
    uv build --wheel
    unzip -l dist/*.whl | grep -E 'templates/|static/|units/'
