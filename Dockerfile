# Container image for the remote MCP server (Cloudflare Containers, linux/amd64).
# Playwright connects to a remote Browserbase browser over CDP; no browser binaries are installed.
FROM ghcr.io/astral-sh/uv:0.13.1 AS uv

FROM python:3.12-slim

COPY --from=uv /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --create-home --uid 10001 app
WORKDIR /app

# Dependencies first so source edits reuse this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY instructions.md ./
RUN uv sync --locked --no-dev && chown -R app:app /app

USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"]

CMD ["uv", "run", "--locked", "--no-dev", "ifd-serve"]
