set dotenv-load := true

default: check

# run the development server
dev:
    uv run dnsrules runserver

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

# print the sha384 of the vendored htmx build
htmx-hash:
    openssl dgst -sha384 -binary src/dnsrules/core/static/dnsrules/htmx.min.js | openssl base64 -A
