"""SimBrief profile recovery and keep-alive. Browserbase is FAKED here (no sessions created)."""

from contextlib import contextmanager, nullcontext
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


@pytest.mark.parametrize(
    "route,found,prompts,timeout,status,finder_clicks",
    [
        (None, "DOTSS2 CLEEE BLH J169 KOFFA SNDBR3", [], False, "generated", 1),
        ("  ", "JCOBY4 SWANN PHLBO4", [], False, "generated", 1),
        ("DCT", "unused", [], False, "generated", 0),
        ("JCOBY4 SWANN PHLBO4", "unused", [], False, "generated", 0),
        (None, "", [], False, "needs_review", 1),
        (None, "DCT", [], False, "needs_review", 1),
        (None, "", ["No route found"], False, "needs_review", 1),
        (None, "EARLY SUGGESTION", ["Native: Route failed"], False, "needs_review", 1),
        (None, "", ["No Alternates Found"], False, "needs_review", 0),
        (None, "", [], True, "timeout", 1),
    ],
)
def test_generation_waits_for_routing_before_claiming_generate(
    monkeypatch, tmp_path, route, found, prompts, timeout, status, finder_clicks
):
    """Controlled form events exercise the real generation flow; no provider calls."""
    from playwright.sync_api import TimeoutError

    class Page:
        url = simbrief_browser.DISPATCH_URL
        finder_clicks = 0
        generate_clicks = 0
        pending_route = False

        def __init__(self):
            self.values = {"route": "EARLY SUGGESTION", "type": "A20N", "origrwy": "30"}

        def on(self, event, callback):
            assert event == "dialog"
            self.dialog_callback = callback

        def remove_listener(self, event, callback):
            assert event == "dialog" and self.dialog_callback is callback
            self.dialog_callback = None

        def select_option(self, selector, value):
            self.values[selector[1:]] = value

        def fill(self, selector, value):
            self.values[selector[1:]] = value

        def dispatch_event(self, *args):
            pass

        def wait_for_function(self, script, **kwargs):
            if self.pending_route:
                if timeout:
                    raise TimeoutError("Route Finder did not finish")
                self.values["route"] = found
                self.pending_route = False

        def evaluate(self, script, arg=None):
            if script == simbrief_browser.SET_DATE_JS:
                self.values["date"] = "09 Nov 2026 - 15:00"
            elif script == simbrief_browser.VISIBLE_MODALS_JS:
                return (
                    [p for p in prompts if not p.startswith("Native:")]
                    if self.finder_clicks or "Alternates" in " ".join(prompts)
                    else []
                )
            elif script == simbrief_browser.SET_CHECKBOX_JS:
                self.values["tlr"] = arg[1]
            else:
                assert "tlr" in script
                return self.values["tlr"]

        def input_value(self, selector):
            return self.values[selector[1:]]

        def get_by_text(self, text, **kwargs):
            def click():
                if text == "Find Route":
                    assert self.values["origrwy"] == "25R"
                    self.finder_clicks += 1
                    self.pending_route = True
                    for prompt in prompts:
                        if prompt.startswith("Native:"):
                            self.dialog_callback(
                                SimpleNamespace(message=prompt, dismiss=lambda: None)
                            )
                else:
                    assert text == "Generate Flight"
                    assert not self.pending_route
                    self.generate_clicks += 1
                    self.url = "https://dispatch.simbrief.com/briefing"

            return SimpleNamespace(click=click)

        def screenshot(self, **kwargs):
            pass

        def wait_for_timeout(self, *args):
            pass

    page = Page()
    browser = SimpleNamespace(contexts=[SimpleNamespace(pages=[page])], close=lambda: None)
    pw = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=lambda _: browser))
    monkeypatch.setattr(simbrief_browser, "sync_playwright", lambda: nullcontext(pw))
    monkeypatch.setattr(simbrief_browser, "_client", lambda: None)
    monkeypatch.setattr(
        simbrief_browser,
        "open_session",
        lambda *a, **k: SimpleNamespace(id="routing-test", connect_url="unused"),
    )
    released = []
    monkeypatch.setattr(simbrief_browser, "release", lambda bb, sid: released.append(sid))
    monkeypatch.setattr(simbrief_browser, "ensure_logged_in", lambda _: True)

    def confirm_time(page):
        # Observed SimBrief behavior: time confirmation can reset runway and routing.
        page.values.update(route="", origrwy="30")
        return ["departure time has changed -> Yes"]

    monkeypatch.setattr(simbrief_browser, "_answer_known_prompts", confirm_time)
    fields = dict(
        origin="KLAX",
        destination="KMIA",
        aircraft="A20N",
        units="KGS",
        callsign="N320HD",
        departure_utc="2026-11-09T15:00:00Z",
        route=route,
        runway="25R",
        tag="routing-test",
    )
    claims = []
    if status == "timeout":
        with pytest.raises(TimeoutError) as exc:
            simbrief_browser.generate(fields, True, tmp_path, lambda: claims.append(True))
        assert exc.value.simbrief_session.endswith("routing-test")
    else:
        result = simbrief_browser.generate(fields, True, tmp_path, lambda: claims.append(True))
        assert result["status"] == status
        if status == "generated":
            assert result["values"]["route"] == (
                route.strip() if route and route.strip() else found
            )
        elif not prompts:
            assert "explicitly approve DCT" in result["reason"]
    assert page.finder_clicks == finder_clicks
    assert page.generate_clicks == len(claims) == int(status == "generated")
    assert page.dialog_callback is None
    assert released == ["routing-test"]


@pytest.fixture
def browser_resources(monkeypatch):
    """Controlled Browserbase + Playwright lifecycle, including thread ownership."""
    from threading import get_ident

    events, browsers, creates = [], [], []

    class Browser:
        def __init__(self, url):
            self.owner = get_ident()
            self.id = url
            self.closed = False
            self.contexts = [SimpleNamespace(pages=[self])]

        def record(self, action):
            assert get_ident() == self.owner and not self.closed
            events.append((action, self.id, get_ident()))

        def close(self):
            self.record("disconnect")
            self.closed = True

        def select_option(self, *args):
            self.record("select")

        def wait_for_function(self, *args, **kwargs):
            self.record("wait")

        def locator(self, *args):
            self.record("locator")
            return self

        def evaluate(self, *args):
            self.record("evaluate")
            return [{"id": "A20N", "name": "Default"}]

    def connect(url):
        browser = Browser(url)
        browsers.append(browser)
        return browser

    @contextmanager
    def playwright():
        events.append(("driver_start", None, get_ident()))
        try:
            yield SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=connect))
        finally:
            events.append(("driver_stop", None, get_ident()))

    def create(**kwargs):
        session = SimpleNamespace(
            id=f"session-{len(creates)}", connect_url=f"session-{len(creates)}"
        )
        creates.append(session)
        return session

    def update(sid, **kwargs):
        assert kwargs == {"status": "REQUEST_RELEASE"}
        events.append(("release", sid, get_ident()))

    client = SimpleNamespace(sessions=SimpleNamespace(create=create, update=update))
    monkeypatch.setattr(simbrief_browser, "_client", lambda: client)
    monkeypatch.setattr(simbrief_browser, "_context_id", lambda _: "saved-login-profile")
    monkeypatch.setattr(simbrief_browser, "sync_playwright", playwright)
    monkeypatch.setattr(simbrief_browser, "ensure_logged_in", lambda _: True)
    return SimpleNamespace(events=events, creates=creates, browsers=browsers, client=client)


def test_workflow_reuses_one_connection_and_preserves_usage_context(browser_resources):
    from ifdispatcher import observability

    resources, usage = browser_resources, []
    token = observability.meter.set(usage)
    try:
        with simbrief_browser.session_scope():
            assert simbrief_browser.airframes("A20N")["status"] == "ok"
            with simbrief_browser.session_scope():
                first = simbrief_browser.keepalive()
            assert simbrief_browser.airframes("A21N")["status"] == "ok"
            assert first["session"].endswith(resources.creates[0].id)
            assert not any(e[0] == "release" for e in resources.events)
        assert len(resources.creates) == len(resources.browsers) == len(usage) == 1
        assert usage[0]["released"] and usage[0]["elapsed_s"] >= 0
        assert [e[0] for e in resources.events][-3:] == ["disconnect", "driver_stop", "release"]
        assert len({e[2] for e in resources.events}) == 1
        assert simbrief_browser._workflow_browser.get() is None
    finally:
        observability.meter.reset(token)


def test_no_browser_work_opens_no_session(browser_resources):
    with simbrief_browser.session_scope():
        pass
    assert browser_resources.creates == browser_resources.events == []


def test_concurrent_workflows_do_not_share_a_browser(browser_resources):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    ready = Barrier(2)

    def workflow():
        with simbrief_browser.session_scope():
            first = simbrief_browser.keepalive()["session"]
            ready.wait(timeout=5)
            assert simbrief_browser.keepalive()["session"] == first
            return first

    with ThreadPoolExecutor(max_workers=2) as pool:
        sessions = list(pool.map(lambda _: workflow(), range(2)))
    assert len(set(sessions)) == len(browser_resources.creates) == 2
    assert all(b.closed for b in browser_resources.browsers)
    assert sum(e[0] == "release" for e in browser_resources.events) == 2


@pytest.mark.parametrize("failure", ["tool", "connect", "release"])
def test_workflow_cleanup_on_failures(browser_resources, monkeypatch, failure):
    resources = browser_resources

    def fail(*args, **kwargs):
        raise RuntimeError(failure)

    if failure == "connect":
        monkeypatch.setattr(simbrief_browser, "sync_playwright", fail)
    if failure == "release":
        monkeypatch.setattr(resources.client.sessions, "update", fail)

    def scenario():
        with simbrief_browser.session_scope():
            simbrief_browser.keepalive()
            if failure == "tool":
                raise RuntimeError("tool")

    if failure == "release":
        scenario()  # cleanup failure must not replace a successful operation with an error
    else:
        with pytest.raises(RuntimeError, match=failure) as exc:
            scenario()
        if failure == "connect":
            assert exc.value.simbrief_session.endswith(resources.creates[0].id)
    assert len(resources.creates) == 1
    if failure != "release":
        assert sum(e[0] == "release" for e in resources.events) == 1
    assert simbrief_browser._workflow_browser.get() is None


def test_parallel_dispatcher_tools_share_session_until_approval(browser_resources, monkeypatch):
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from ifdispatcher import agent, observability
    from test_agent_workflow import ScriptedModel

    monkeypatch.setattr(agent.flights, "airport_name", lambda _: "Test airport")
    monkeypatch.setattr(agent.flights, "airport_elevation", lambda _: 312)
    monkeypatch.setattr(agent.flights, "local_time", lambda value, _: value)
    monkeypatch.setattr(observability, "write_feedback", lambda *args: None)
    model = ScriptedModel(
        [
            AIMessage(
                "",
                tool_calls=[
                    {"id": "a20n", "name": "simbrief_airframes", "args": {"aircraft": "A20N"}},
                    {"id": "a21n", "name": "simbrief_airframes", "args": {"aircraft": "A21N"}},
                ],
            ),
            AIMessage(
                "",
                tool_calls=[
                    {
                        "id": "dispatch",
                        "name": "dispatch_flight",
                        "args": dict(
                            trip="scope-test",
                            leg="1",
                            origin="KIAD",
                            destination="KEWR",
                            sim_aircraft="A20N",
                            departure_local_date="2026-11-09",
                            departure_utc="2026-11-09T12:00:00Z",
                            private_callsign="N320HD",
                        ),
                    }
                ],
            ),
        ]
    )
    graph = agent.build_agent(model=model, checkpointer=InMemorySaver())
    monkeypatch.setattr(remote, "_get_agent", lambda: graph)
    result = remote._run({"messages": [{"role": "user", "content": "Prepare my flight"}]}, "scope")
    assert result["status"] == "approval_required"
    assert len(browser_resources.creates) == len(browser_resources.browsers) == 1
    assert browser_resources.browsers[0].closed
    assert result["provider_usage"][0]["released"]
