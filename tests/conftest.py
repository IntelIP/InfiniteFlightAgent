"""Run the suite against Postgres when TEST_DATABASE_URL is set (e.g. a local scratch cluster)."""

import os

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
        for table in ("requests", "snapshots", "leg_meta"):
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    yield
