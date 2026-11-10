"""Real local admission and controlled provider termination; no external browsers."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from ifdispatcher import browser_budget as budget, remote, simbrief_browser


@pytest.fixture(autouse=True)
def local_store(tmp_path, monkeypatch):
    monkeypatch.setenv("IFD_DATA_DIR", str(tmp_path))


def test_fifo_overflow_and_expiry_remove_waiting_reservations(monkeypatch):
    monkeypatch.setattr(budget, "QUEUE_SECONDS", 0.3)
    first, second, third = budget.Lease(), budget.Lease(), budget.Lease()
    first.acquire()
    with ThreadPoolExecutor(2) as pool:
        waiting = pool.submit(second.acquire)
        while budget.admission_status()["waiting"] < 1:
            time.sleep(0.005)
        last = pool.submit(third.acquire)
        while budget.admission_status()["waiting"] < 2:
            time.sleep(0.005)
        with pytest.raises(budget.BrowserLimit, match="queue_full"):
            budget.Lease().acquire()
        first.finish(True)
        waiting.result(1)
        assert budget.admission_status()["active"] == 1
        assert not last.done()
        with pytest.raises(budget.BrowserLimit, match="queue_timeout"):
            last.result(1)
        assert budget.admission_status()["waiting"] == 0
        second.finish(True)
    assert budget.admission_status()["active"] == 0


def test_unconfirmed_release_keeps_lease_until_provider_expiry(monkeypatch):
    owner = budget.Lease()
    owner.acquire()
    owner.fence_create()
    owner.finish(False)
    assert budget.admission_status()["active"] == 1
    now = time.time()
    monkeypatch.setattr(budget.time, "time", lambda: now + 300)
    assert budget.admission_status()["active"] == 0
    replacement = budget.Lease()
    replacement.acquire()
    owner.finish(True)  # an old owner cannot clear a newer lease
    assert budget.admission_status()["active"] == 1
    replacement.finish(True)


def test_api_client_has_short_timeout_and_no_automatic_retries(monkeypatch):
    monkeypatch.setenv("BROWSERBASE_API_KEY", "test-key")
    with simbrief_browser._client() as client:
        assert client.timeout == budget.API_SECONDS
        assert client.max_retries == 0


def test_old_cron_no_longer_opens_a_browser(monkeypatch):
    monkeypatch.setenv("IFD_PAID_OPERATIONS_ENABLED", "true")
    monkeypatch.setattr(simbrief_browser, "keepalive", lambda: pytest.fail("must not open"))
    result = asyncio.run(remote.simbrief_keepalive(None))
    assert result.status_code == 200
    assert b'"status":"skipped"' in result.body


def test_remote_admission_rejects_before_submitting_work(monkeypatch):
    from concurrent.futures import Future

    monkeypatch.setattr(remote, "_turns", {str(n): Future() for n in range(6)})
    monkeypatch.setattr(remote._pool, "submit", lambda *a: pytest.fail("must not submit"))
    result = asyncio.run(remote.plan_flight("new flight"))
    assert result["status"] == "queue_full"


def test_cleanup_only_ends_aged_dispatcher_sessions(monkeypatch):
    now = datetime.now(timezone.utc)

    def session(sid, seconds, owned=True):
        return SimpleNamespace(
            id=sid,
            status="RUNNING",
            started_at=now - timedelta(seconds=seconds),
            created_at=now - timedelta(seconds=seconds),
            user_metadata={"app": "InfiniteFlightDispatcher" if owned else "OtherApp"},
        )

    sessions = [session("old", 300), session("young", 10), session("unrelated", 900, False)]
    released = []

    def update(sid, **kwargs):
        assert kwargs == {"status": "REQUEST_RELEASE"}
        released.append(sid)
        return SimpleNamespace(status="COMPLETED")

    client = SimpleNamespace(
        sessions=SimpleNamespace(
            list=lambda: sessions,
            retrieve=lambda sid: next(s for s in sessions if s.id == sid),
            update=update,
        )
    )
    monkeypatch.setattr(simbrief_browser, "_client", lambda: client)
    assert len(simbrief_browser.session_inventory()["sessions"]) == 3
    assert released == []
    rows = simbrief_browser.session_inventory(cleanup=True)["sessions"]
    assert released == ["old"]
    assert rows[0]["released"] is True


def test_release_request_is_not_reported_as_confirmed_completion():
    client = SimpleNamespace(
        sessions=SimpleNamespace(
            update=lambda *a, **k: SimpleNamespace(status="RUNNING"),
            retrieve=lambda *a: SimpleNamespace(status="RUNNING"),
        )
    )
    assert simbrief_browser.release(client, "not-yet-stopped") is False


def test_already_completed_session_needs_no_release_request():
    from ifdispatcher import observability

    usage = []
    token = observability.meter.set(usage)
    client = SimpleNamespace(
        sessions=SimpleNamespace(
            retrieve=lambda *a: SimpleNamespace(status="COMPLETED"),
            update=lambda *a, **k: pytest.fail("completed session needs no update"),
        )
    )
    try:
        observability.browser_opened("already-ended")
        assert simbrief_browser.release(client, "already-ended")
        assert usage[0]["released"] is True
        assert usage[0]["release_requested"] is False
    finally:
        observability.meter.reset(token)
