"""SimBrief profile recovery and keep-alive. Browserbase is FAKED here (no sessions created)."""

from types import SimpleNamespace

import httpx
import pytest
from browserbase import NotFoundError

from ifdispatcher import remote, simbrief_browser
from ifdispatcher.core import open_store


class FakeContexts:
    def __init__(self, *existing):
        self.existing = set(existing)
        self.created = []

    def retrieve(self, context_id):
        if context_id not in self.existing:
            request = httpx.Request("GET", f"https://api.browserbase.com/v1/contexts/{context_id}")
            raise NotFoundError(
                "Context ID not found", response=httpx.Response(404, request=request), body=None
            )
        return SimpleNamespace(id=context_id)

    def create(self):
        context_id = f"new-{len(self.created) + 1}"
        self.created.append(context_id)
        self.existing.add(context_id)
        return SimpleNamespace(id=context_id)


@pytest.fixture(autouse=True)
def store_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("IFD_DATA_DIR", str(tmp_path))
    monkeypatch.delenv(simbrief_browser.CONTEXT_SETTING, raising=False)


def bb(*existing):
    return SimpleNamespace(contexts=FakeContexts(*existing))


def test_configured_profile_is_used_while_it_exists(monkeypatch):
    monkeypatch.setenv(simbrief_browser.CONTEXT_SETTING, "configured")
    client = bb("configured")
    assert simbrief_browser._context_id(client) == "configured"
    assert client.contexts.created == []


def test_deleted_profile_is_recreated_once_and_remembered(monkeypatch):
    monkeypatch.setenv(simbrief_browser.CONTEXT_SETTING, "deleted")
    client = bb()
    assert simbrief_browser._context_id(client) == "new-1"
    assert simbrief_browser._context_id(client) == "new-1"  # reused, not recreated
    assert client.contexts.created == ["new-1"]
    assert open_store().read_setting(simbrief_browser.STORED_CONTEXT) == "new-1"


def test_sign_in_is_skipped_without_credentials(monkeypatch):
    monkeypatch.delenv("NAVIGRAPH_USERNAME", raising=False)
    monkeypatch.delenv("NAVIGRAPH_PASSWORD", raising=False)
    page = SimpleNamespace(goto=lambda *a, **k: pytest.fail("must not navigate"))
    assert simbrief_browser._sign_in(page) is False


def test_keepalive_route_respects_the_kill_switch(monkeypatch):
    from starlette.testclient import TestClient

    monkeypatch.setenv("IFD_INTERNAL_TOKEN", "t")
    monkeypatch.setenv("IFD_PAID_OPERATIONS_ENABLED", "false")
    monkeypatch.setattr(simbrief_browser, "keepalive", lambda: pytest.fail("must not run"))
    client = TestClient(remote.create_app())
    path = "/internal/simbrief/keepalive"
    assert client.post(path).status_code == 401
    response = client.post(path, headers={remote.TOKEN_HEADER: "t"})
    assert response.json() == {"status": "paid_operations_disabled"}
