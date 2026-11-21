# Container image for the remote MCP server (Cloudflare Containers, linux/amd64).
# Playwright connects to a remote Browserbase browser over CDP; no browser binaries are installed.
FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv

FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928

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
RUN uv sync --locked --no-dev && chmod -R go-w /app/.venv /app/src && install -d -o app -g app -m 700 /app/data

USER app
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"]

CMD ["/app/.venv/bin/ifd-serve"]
