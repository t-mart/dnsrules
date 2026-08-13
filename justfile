set dotenv-load := true

default: check

# run the development server, rebuilding css on every change
dev: var
    uv run dnsrules tailwind runserver

# run a management command with the development environment loaded
manage *ARGS:
    uv run dnsrules {{ ARGS }}

# stand in for the router's /etc/unbound, which no development machine has
var:
    mkdir --parents var

# write a stand-in for the inventory that Ansible renders on the router
inventory: var
    #!/usr/bin/env bash
    set -euo pipefail
    cat > var/inventory.yml <<EOF
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
    EOF
    echo "Wrote var/inventory.yml."

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

# build the wheel and confirm it carries the templates and static files
wheel:
    rm -rf dist
    uv build --wheel
    unzip -l dist/*.whl | grep -E 'templates/|static/'

# print the sha384 of the vendored htmx build
htmx-hash:
    openssl dgst -sha384 -binary src/dnsrules/static/dnsrules/htmx.min.js | openssl base64 -A
