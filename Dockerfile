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

# dnsrules writes no file, and both ports are above 1024, so nothing here needs
# root. The tree stays owned by root and is read only to this user.
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin dnsrules
USER dnsrules

# The site answers, Django renders, and the database replies. `/login/` needs no
# session, and it is the one page a healthcheck can reach. There is no curl in
# this image, and there is a Python.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/login/', timeout=4)"]

CMD ["dnsrules", "serve"]
