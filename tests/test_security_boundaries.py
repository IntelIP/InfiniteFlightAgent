"""Persistence and hosted paid-work regression checks. Provider calls use a fake."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from ifdispatcher import flights
from ifdispatcher.core import open_store


def test_setting_text_round_trip():
    store = open_store()
    value = "Pilot's note: <leg one> & leg two?"
    store.save_setting("route-note", value)
    assert store.read_setting("route-note") == value


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires scratch Postgres")
def test_paid_admission_and_stop(monkeypatch):
    import psycopg

    from ifdispatcher.migrate import migrate

    dsn = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("IFD_HOSTED", "1")
    monkeypatch.setenv("IFD_PAID_OPERATIONS_ENABLED", "true")
    monkeypatch.setenv("AEROAPI_KEY", "fixture")
    monkeypatch.setattr(flights, "_cache", {})
    monkeypatch.setattr(flights, "_recent", [])
    calls = []

    def provider(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(provider)

    def dispatch(i):
        try:
            flights._get(f"/flights/TEST{i}", transport=transport)
        except ValueError as exc:
            return str(exc)
        return "ok"

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("TRUNCATE aeroapi_usage")
        conn.execute("UPDATE paid_policy SET stopped=false, daily_pages=2")
        with ThreadPoolExecutor(max_workers=2) as workers:
            outcomes = list(workers.map(dispatch, range(6)))
        assert outcomes.count("ok") == len(calls) == 2
        assert outcomes.count("daily_aeroapi_allowance_exhausted") == 4
        assert flights._get(calls[0].removeprefix("/aeroapi"), transport=transport) == {}
        flights._cache.clear()
        assert dispatch(7) == "daily_aeroapi_allowance_exhausted"
        with ThreadPoolExecutor(max_workers=1) as workers:
            candidate = workers.submit(migrate, dsn)
            assert conn.execute("SELECT public.stop_jumpseat()").fetchone() == (True,)
            candidate.result()
        subprocess.run(
            [sys.executable, "-c", "from ifdispatcher.config import paid_operations_enabled; "
             "assert not paid_operations_enabled()"],
            check=True,
        )
        assert "paid_operations_disabled" in dispatch(8)
        assert len(calls) == 2
        conn.execute("UPDATE paid_policy SET stopped=false, daily_pages=3")
        assert dispatch(9) == "ok"
