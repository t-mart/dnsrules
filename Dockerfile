# One image, one process. `serve` runs the website, the query log ingest, and
# the recurring jobs in a single container.

FROM ghcr.io/astral-sh/uv:python3.14-trixie-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH" \
    # Without this, migrate and every log line sit in a buffer until the
    # process ends, so a startup fault reaches the journal after the restart.
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, and from the lock file alone, so a source edit never
# refetches them. README.md comes too, because pyproject.toml names it.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

# 8000 is the website, and the RPZ zone that unbound fetches. 6000 takes the
# dnstap stream, which unbound connects out to.
EXPOSE 8000 6000

CMD ["dnsrules", "serve"]
