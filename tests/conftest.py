"""Run the suite against Postgres when TEST_DATABASE_URL is set (e.g. a local scratch cluster)."""

import os

import httpx
import pytest

TEST_DSN = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def database(monkeypatch):
    if not TEST_DSN:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        yield
        return
    import psycopg

    monkeypatch.setenv("DATABASE_URL", TEST_DSN)
    with psycopg.connect(TEST_DSN) as conn:
        for table in ("requests", "snapshots", "leg_meta", "settings"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    yield


LOCAL = ("127.0.0.1", "localhost")


@pytest.fixture(autouse=True)
def no_internet(monkeypatch, tmp_path_factory):
    """Tests never reach a provider: a missed stub fails instead of making a paid call.

    Only the in-process test server (localhost) is reachable, and each run gets an empty
    airport cache instead of the user's real one.
    """
    real, real_async = (
        httpx.HTTPTransport.handle_request,
        httpx.AsyncHTTPTransport.handle_async_request,
    )

    def guard(request):
        if request.url.host not in LOCAL:
            raise httpx.ConnectError(f"tests must not reach {request.url.host}", request=request)

    def handle(self, request):
        guard(request)
        return real(self, request)

    async def handle_async(self, request):
        guard(request)
        return await real_async(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle_async)
    monkeypatch.setenv("IFD_AIRPORT_CACHE_DIR", str(tmp_path_factory.mktemp("airports")))
