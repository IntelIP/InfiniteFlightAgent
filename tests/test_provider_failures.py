"""Generation failure journeys with real SDK errors and local storage; no provider calls."""

import json
import time
from contextlib import nullcontext
from types import SimpleNamespace

import httpx
import pytest
from browserbase import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from ifdispatcher import simbrief_browser, workflow
from ifdispatcher.core import open_store


def status_error(status, body):
    request = httpx.Request("POST", "https://api.browserbase.com/v1/sessions")
    return APIStatusError(
        "private provider diagnostic", response=httpx.Response(status, request=request), body=body
    )


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    monkeypatch.setenv("IFD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IFD_PAID_OPERATIONS_ENABLED", "true")
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setattr(workflow.artifacts, "upload", lambda *args: [])
    assert (
        workflow.dispatch_flight(
            "provider-test",
            "1",
            "KIAD",
            "KEWR",
            "A20N",
            "2026-11-09",
            departure_utc="2026-11-09T15:00:00Z",
            private_callsign="N320HD",
            route="DCT",
        )["status"]
        == "awaiting_simbrief_generation"
    )


def failing_provider(monkeypatch, error):
    attempts = []

    def create(**kwargs):
        attempts.append(kwargs)
        raise error

    client = SimpleNamespace(sessions=SimpleNamespace(list=lambda: [], create=create))
    monkeypatch.setattr(simbrief_browser, "_client", lambda: client)
    monkeypatch.setattr(simbrief_browser, "_context_id", lambda _: "controlled-context")
    monkeypatch.setattr(
        simbrief_browser, "sync_playwright", lambda: pytest.fail("must not connect after failure")
    )
    return attempts


@pytest.mark.parametrize(
    "status,body,code",
    [
        (402, {"message": "Monthly browser hours quota exceeded"}, "provider_quota_exhausted"),
        (402, {"message": "Browser minutes exhausted"}, "provider_quota_exhausted"),
        (402, {"message": "Browser minutes limit exceeded"}, "provider_quota_exhausted"),
        (402, {"message": "Insufficient browser minutes"}, "provider_quota_exhausted"),
        (
            402,
            {"message": "You have reached the monthly browser minutes limit"},
            "provider_quota_exhausted",
        ),
        (429, {"error": {"code": "CONCURRENCY_LIMIT_EXCEEDED"}}, "provider_concurrency_limited"),
        (401, {"message": "Invalid API key"}, "provider_authentication_failed"),
        (403, {"message": "Project access denied"}, "provider_authentication_failed"),
        (503, {"message": "Service unavailable"}, "provider_unavailable"),
        (504, None, "provider_timeout"),
        (402, {"message": "Payment required"}, "provider_payment_required"),
        (429, {"message": "Too many requests"}, "provider_rate_limited"),
        (
            429,
            {"message": "Concurrency is available; creation rate limit exceeded"},
            "provider_rate_limited",
        ),
        (400, {"message": "Quota is not exhausted"}, "provider_error_unknown"),
        (400, {"message": "Browser minutes are available"}, "provider_error_unknown"),
        (400, {"message": "Unspecified failure"}, "provider_error_unknown"),
    ],
)
def test_provider_failure_is_sanitized_and_saved_before_click(
    prepared, monkeypatch, status, body, code
):
    # Unknown fields and the SDK message may contain credentials or signed URLs.
    if body is not None:
        body = {**body, "private": "sensitive-marker"}
    attempts = failing_provider(monkeypatch, status_error(status, body))
    with simbrief_browser.session_scope():
        result = workflow.generate_plan("provider-test", "1")
        saved = open_store().read_meta("provider-test", "1", 1)["generation"]
        assert result["status"] == saved["status"] == "error"
        assert result["error"] == "APIStatusError"
        assert result["reason_code"] == code
        assert result["provider_status_code"] == status
        assert result["clicked"] is False and result["retryable"] is True
        assert result["automatic_retry_allowed"] is False
        assert result["reason"] and result["next"]
        assert saved == result
        assert "private provider diagnostic" not in json.dumps(saved)
        assert "sensitive-marker" not in json.dumps(saved)
        assert "at" not in saved  # no Generate claim
        # Re-entering generation in this stopped scope cannot create a replacement.
        again = workflow.generate_plan("provider-test", "1")
        assert again["automatic_retry_allowed"] is False
    assert len(attempts) == 1


class GenerationPage:
    url = simbrief_browser.DISPATCH_URL
    generate_clicks = 0

    def __init__(self, error):
        self.error = error
        self.values = {"type": "A20N", "origrwy": "30"}

    def on(self, *args):
        pass

    def remove_listener(self, *args):
        pass

    def select_option(self, selector, value):
        self.values[selector[1:]] = value

    def fill(self, selector, value):
        self.values[selector[1:]] = value

    def dispatch_event(self, *args):
        pass

    def wait_for_function(self, *args, **kwargs):
        pass

    def evaluate(self, script, arg=None):
        if script == simbrief_browser.SET_DATE_JS:
            self.values["date"] = "09 Nov 2026 - 15:00"
        elif script == simbrief_browser.SET_CHECKBOX_JS:
            self.values["tlr"] = arg[1]
        elif script == simbrief_browser.VISIBLE_MODALS_JS:
            return []
        else:
            return self.values["tlr"]

    def input_value(self, selector):
        return self.values[selector[1:]]

    def screenshot(self, **kwargs):
        pass

    def get_by_text(self, text, **kwargs):
        assert text == "Generate Flight"

        def click():
            self.generate_clicks += 1

        return SimpleNamespace(click=click)

    def wait_for_timeout(self, *args):
        if self.error:
            raise self.error


def connected_provider(monkeypatch, page):
    context = SimpleNamespace(
        pages=[page],
        set_default_timeout=lambda _: None,
        set_default_navigation_timeout=lambda _: None,
    )
    browser = SimpleNamespace(contexts=[context], close=lambda: None)
    driver = SimpleNamespace(chromium=SimpleNamespace(connect_over_cdp=lambda *a, **k: browser))
    created, released = [], []

    def create(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(id="controlled-session", connect_url="unused")

    client = SimpleNamespace(sessions=SimpleNamespace(list=lambda: [], create=create))
    monkeypatch.setattr(simbrief_browser, "_client", lambda: client)
    monkeypatch.setattr(simbrief_browser, "_context_id", lambda _: "controlled-context")
    monkeypatch.setattr(simbrief_browser, "sync_playwright", lambda: nullcontext(driver))
    monkeypatch.setattr(simbrief_browser, "ensure_logged_in", lambda _: True)
    monkeypatch.setattr(simbrief_browser, "_answer_known_prompts", lambda _: [])

    def release(*args):
        released.append(True)
        return True

    monkeypatch.setattr(simbrief_browser, "release", release)
    return created, released


@pytest.mark.parametrize(
    "error,code",
    [
        (
            APITimeoutError(
                request=httpx.Request("POST", "https://api.browserbase.com/v1/sessions")
            ),
            "provider_timeout",
        ),
        (PlaywrightTimeoutError("private browser diagnostic"), "provider_timeout"),
        (status_error(503, {"message": "Unavailable"}), "provider_unavailable"),
        (RuntimeError("private browser diagnostic"), "provider_error_unknown"),
    ],
)
def test_failure_after_generate_preserves_claim_and_blocks_another_click(
    prepared, monkeypatch, error, code
):
    page = GenerationPage(error)
    created, released = connected_provider(monkeypatch, page)
    first = workflow.generate_plan("provider-test", "1")
    saved = open_store().read_meta("provider-test", "1", 1)["generation"]
    assert first["status"] == saved["status"] == "uncertain"
    assert first["error"] == type(error).__name__
    assert first["reason_code"] == code
    assert first["clicked"] is True and first["retryable"] is False
    assert first["automatic_retry_allowed"] is False
    assert "unknown" in first["reason"].lower()
    assert "Do not click Generate again" in first["next"]
    assert "Inspect saved generation status" in first["next"]
    assert "ask the user to inspect and confirm the existing SimBrief plan" in first["next"]
    assert (
        "Only call finalize_dispatch after the user confirms the plan was generated"
        in first["next"]
    )
    assert "retrying" not in first["next"]
    assert "private" not in json.dumps(saved)
    assert saved["at"]
    assert workflow.generate_plan("provider-test", "1")["status"] == "already_attempted"
    assert open_store().read_meta("provider-test", "1", 1)["generation"] == saved
    assert page.generate_clicks == len(created) == len(released) == 1


def test_provider_failure_reaches_final_graph_state(prepared, monkeypatch):
    from langchain_core.messages import AIMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from ifdispatcher import agent
    from test_agent_workflow import ScriptedModel

    request = httpx.Request("POST", "https://api.browserbase.com/v1/sessions")
    attempts = failing_provider(
        monkeypatch,
        RateLimitError(
            "quota exhausted",
            response=httpx.Response(429, request=request),
            body={"message": "quota exhausted"},
        ),
    )
    graph = agent.build_agent(
        model=ScriptedModel(
            [
                AIMessage(
                    "",
                    tool_calls=[
                        {
                            "id": "generate",
                            "name": "generate_in_simbrief",
                            "args": {"trip": "provider-test", "leg": "1"},
                        }
                    ],
                ),
                AIMessage("Browser quota is exhausted; generation was not clicked."),
            ]
        ),
        checkpointer=InMemorySaver(),
    )
    config = {"configurable": {"thread_id": "provider-failure"}}
    result = graph.invoke(
        {"messages": [{"role": "user", "content": "Generate approved leg"}]}, config, version="v2"
    )
    assert not result.interrupts
    tool_result = next(m for m in result.value["messages"] if m.type == "tool")
    failure = json.loads(tool_result.content)
    assert failure["reason_code"] == "provider_quota_exhausted"
    assert failure["automatic_retry_allowed"] is False
    assert failure["clicked"] is False
    assert graph.get_state(config).next == ()
    assert open_store().read_meta("provider-test", "1", 1)["generation"] == failure
    assert len(attempts) == 1


def test_unobserved_completion_is_saved_as_unknown_without_another_click(prepared, monkeypatch):
    page = GenerationPage(None)
    created, released = connected_provider(monkeypatch, page)
    result = workflow.generate_plan("provider-test", "1")
    saved = open_store().read_meta("provider-test", "1", 1)["generation"]
    assert result["status"] == saved["status"] == "uncertain"
    assert result["reason_code"] == "generation_outcome_unknown"
    assert result["automatic_retry_allowed"] is False
    assert result["retryable"] is False and result["clicked"] is True
    assert "Do not click Generate again" in result["next"]
    assert "Inspect saved generation status" in result["next"]
    assert "ask the user to inspect and confirm the existing SimBrief plan" in result["next"]
    assert (
        "Only call finalize_dispatch after the user confirms the plan was generated"
        in result["next"]
    )
    assert saved["at"]
    assert workflow.generate_plan("provider-test", "1")["status"] == "already_attempted"
    assert page.generate_clicks == len(created) == len(released) == 1


@pytest.mark.parametrize("stopped", ["browser_deadline", "browser_idle_timeout"])
def test_expired_workflow_never_opens_a_replacement(prepared, monkeypatch, stopped):
    page = GenerationPage(RuntimeError("unused"))
    created, released = connected_provider(monkeypatch, page)
    with simbrief_browser.session_scope() as scope:
        scope.run(scope.connect, 1)
        scope.timer.cancel()
        if stopped == "browser_deadline":
            scope.expires = time.monotonic() - 1
        else:
            scope.last_used = time.monotonic() - 31
        scope._watch()
        result = workflow.generate_plan("provider-test", "1")
        assert result["error"] == "BrowserLimit"
        assert result["automatic_retry_allowed"] is False
        assert result["clicked"] is False
    assert page.generate_clicks == 0
    assert len(created) == len(released) == 1


def test_sdk_connection_error_before_click_is_saved(prepared, monkeypatch):
    error = APIConnectionError(
        request=httpx.Request("POST", "https://api.browserbase.com/v1/sessions")
    )
    attempts = failing_provider(monkeypatch, error)
    result = workflow.generate_plan("provider-test", "1")
    assert result["reason_code"] == "provider_unavailable"
    assert result["error"] == "APIConnectionError"
    assert result["clicked"] is False
    assert len(attempts) == 1
