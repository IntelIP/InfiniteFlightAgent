"""SimBrief data entry on a Browserbase cloud browser with a persistent logged-in profile.

The Browserbase context persists SimBrief's cookies between sessions. When a session finds
SimBrief signed out, it signs in through Navigraph's email/password form with
NAVIGRAPH_USERNAME / NAVIGRAPH_PASSWORD (never logged or returned); without them, the user signs
in once through the live view (`ifd-simbrief`). If Browserbase no longer has the configured
context, a new one is created and its id kept in the store. A daily keep-alive refreshes the
login. Generation is an external write: callers must have the user's approval, fill once, verify
the fields, and click Generate at most once per approved dispatch.
"""

import json
import logging
import re
import time
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar, copy_context
from functools import wraps
from pathlib import Path
from threading import Lock, RLock, Timer, get_ident
from typing import Any

from browserbase import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    Browserbase,
    NotFoundError,
)
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from ifdispatcher.config import require_paid_operations, setting
from ifdispatcher import browser_budget as budget, observability

HOME_URL = "https://www.simbrief.com/home/"
DISPATCH_URL = "https://dispatch.simbrief.com/options/custom"
CONTEXT_SETTING = "BROWSERBASE_SIMBRIEF_CONTEXT_ID"
STORED_CONTEXT = "browserbase_simbrief_context_id"  # store key for a context this server created
NAVIGRAPH_LOGIN = re.compile(r"identity\.api\.navigraph\.com")
SIMBRIEF = re.compile(r"simbrief\.com")
UNCERTAIN_GENERATION_NEXT = (
    "Do not click Generate again for this revision. Inspect saved generation status and ask "
    "the user to inspect and confirm the existing SimBrief plan. Only call finalize_dispatch "
    "after the user confirms the plan was generated. If no matching plan exists, ask the user "
    "how to proceed before approving a new revision."
)
_workflow_browser = ContextVar("ifd_workflow_browser", default=None)
log = logging.getLogger(__name__)


def generation_failure(exc: Exception, clicked: bool) -> dict[str, Any]:
    """Static recovery advice from actual error evidence, never raw provider diagnostics.

    A 429 alone does not distinguish concurrency from session creation rate limits.
    A 402 alone establishes a payment problem, not exhausted browser hours. Response
    bodies can contain credentials or URLs: use them only for classification.
    """
    code = "provider_error_unknown"
    reason = "Browser generation failed without a recognized provider cause."
    next_action = (
        "Inspect browser status and configuration before explicitly retrying in a new workflow."
    )
    status = exc.status_code if isinstance(exc, APIStatusError) else None
    if isinstance(exc, budget.BrowserLimit):
        code = "browser_limited"
        reason = str(exc)  # locally defined budget messages; preserve the existing response
        next_action = "This browser workflow has stopped; check browser status before starting a new workflow."
    elif isinstance(exc, (APITimeoutError, PlaywrightTimeoutError, TimeoutError)) or status in (
        408,
        504,
    ):
        code = "provider_timeout"
        reason = "The browser operation timed out."
        next_action = "Check browser status for an unfinished session before explicitly retrying in a new workflow."
    elif status in (401, 403):
        code = "provider_authentication_failed"
        reason = "Browserbase rejected authentication or project access."
        next_action = (
            "Check the configured Browserbase credentials and project access before resuming."
        )
    elif isinstance(exc, APIStatusError):
        body = exc.body
        if isinstance(body, dict):
            error = body.get("error")
            parts = [body.get("code"), body.get("message"), error]
            if isinstance(error, dict):
                parts = [
                    body.get("code"),
                    body.get("message"),
                    error.get("code"),
                    error.get("message"),
                ]
        else:
            parts = [body]
        evidence = " ".join(p for p in parts if isinstance(p, str)).lower()
        evidence = re.sub(r"[_\s-]+", " ", evidence)
        if re.search(
            r"\b(?:quota|credits?|browser (?:hours?|minutes?)|browser time|usage)(?: limit)? "
            r"(?:(?:has|have) been |is |was )?(?:exceeded|exhausted|reached|depleted)\b|"
            r"\b(?:insufficient|exhausted) (?:credits?|quota|browser (?:hours?|minutes?))\b|"
            r"\b(?:exceeded|reached) (?:your |the )?(?:monthly )?"
            r"(?:quota|browser (?:hours?|minutes?)|browser time|usage)(?: limit)?\b",
            evidence,
        ):
            code = "provider_quota_exhausted"
            reason = "Browserbase reported exhausted usage quota or credits."
            next_action = "Check Browserbase usage and quota; resume only after quota is available, or generate manually in SimBrief."
        elif re.search(
            r"\b(?:concurrency|concurrent (?:sessions?|browsers?))(?: limit)? "
            r"(?:has been |was |is )?(?:exceeded|exhausted|reached)\b|"
            r"\b(?:exceeded|reached) (?:your |the )?(?:maximum(?: number of)? |max )?"
            r"(?:concurrency|concurrent (?:sessions?|browsers?))(?: limit)?\b",
            evidence,
        ):
            code = "provider_concurrency_limited"
            reason = "Browserbase reported a concurrent browser limit."
            next_action = "Wait for active browsers to finish and check browser status before explicitly resuming."
        elif status == 402:
            code = "provider_payment_required"
            reason = "Browserbase requires a billing or payment action; exhausted quota was not established."
            next_action = "Check Browserbase billing status before resuming, or generate manually in SimBrief."
        elif status == 429:
            code = "provider_rate_limited"
            reason = "Browserbase rate limited the request; the specific limit was not established."
            next_action = "Wait and check Browserbase rate limits and active sessions before explicitly resuming."
        elif status >= 500:
            code = "provider_unavailable"
            reason = "Browserbase returned a server error."
            next_action = "Check Browserbase service and browser status before explicitly retrying in a new workflow."
    elif isinstance(exc, APIConnectionError):
        code = "provider_unavailable"
        reason = "The Browserbase API could not be reached."
        next_action = (
            "Check connectivity and browser status before explicitly retrying in a new workflow."
        )
    if clicked:
        reason += " Generate was claimed; its outcome is unknown."
        next_action = UNCERTAIN_GENERATION_NEXT
    result = {
        "reason_code": code,
        "reason": reason,
        "next": next_action,
        "automatic_retry_allowed": False,
    }
    if status is not None:
        result["provider_status_code"] = status
    return result


class _WorkflowBrowser:
    """One lazy connection, owned by one thread because Playwright is thread-bound."""

    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="simbrief-browser")
        self.stack = ExitStack()
        self.lock = RLock()
        self.used = False
        self.closed = False
        self.session = None
        self.page = None
        self.owner = None
        self.lease = None
        self.timer = None
        self.expires = None
        self.last_used = time.monotonic()
        self.busy = 0
        self.stopped = None
        self.release_lock = Lock()
        self.release_attempted = False
        self.release_confirmed = False
        self.usage_context = copy_context()

    def remaining(self):
        if self.closed:
            raise budget.BrowserLimit("browser_scope_closed: no further browser commands")
        if self.stopped:
            raise budget.BrowserLimit(self.stopped)
        left = self.expires - time.monotonic() if self.expires else budget.SESSION_SECONDS
        if left <= 0:
            self.abort("browser_deadline: three-minute session budget exhausted")
            raise budget.BrowserLimit(self.stopped)
        return left

    def _release_remote(self):
        with self.release_lock:
            if self.release_attempted or self.session is None:
                return
            self.release_attempted = True
            self.release_confirmed = release(self.bb, self.session.id)
            if self.closed and self.lease:
                self.lease.finish(self.release_confirmed)

    def abort(self, reason):
        with self.lock:
            self.stopped = self.stopped or reason
        observability.event("browserbase", outcome=reason.split(":")[0])
        try:
            self._release_remote()
        except Exception as exc:
            log.warning("SimBrief forced release failed: %s", type(exc).__name__)

    def _watch(self):
        with self.lock:
            if self.closed or self.stopped:
                return
            now = time.monotonic()
            left = self.expires - now
            if not self.busy:
                left = min(left, budget.IDLE_SECONDS - (now - self.last_used))
        if left <= 0:
            reason = "browser_deadline" if now >= self.expires else "browser_idle_timeout"
            self.abort(f"{reason}: session released; no automatic replacement")
            return
        self.timer = Timer(min(left, 1), lambda: self.usage_context.copy().run(self._watch))
        self.timer.daemon = True
        self.timer.start()

    def run(self, call, *args, **kwargs):
        if self.owner == get_ident():
            self.remaining()
            return call(*args, **kwargs)
        with self.lock:
            if self.closed:
                raise ValueError("SimBrief workflow browser is already closed")
            self.remaining()
            self.used = True
            self.busy += 1
            self.last_used = time.monotonic()
            future = self.pool.submit(copy_context().run, self._call, call, args, kwargs)
        try:
            return future.result(
                timeout=budget.QUEUE_SECONDS + budget.SESSION_SECONDS + budget.API_SECONDS * 3
            )
        except TimeoutError:
            if future.done():
                raise
            self.abort(
                "browser_command_timeout: work stopped; check saved generation before retrying"
            )
            future.cancel()
            raise budget.BrowserLimit(self.stopped) from None
        finally:
            with self.lock:
                self.busy -= 1
                self.last_used = time.monotonic()

    def _call(self, call, args, kwargs):
        self.remaining()
        result = call(*args, **kwargs)
        self.remaining()
        return result

    def connect(self, minutes):
        require_paid_operations()
        self.owner = get_ident()
        try:
            if self.session is not None and self.page is None:
                raise ValueError(
                    "SimBrief workflow browser could not connect; start a new workflow"
                )
            if self.session is None:
                self.lease = budget.Lease()
                self.lease.acquire()
                self.expires = time.monotonic() + budget.SESSION_SECONDS
                self.bb = _client()
                self.session = open_session(
                    self.bb, minutes=min(minutes, budget.SESSION_SECONDS / 60)
                )
                # LIFO cleanup: disconnect, stop Playwright, then release Browserbase even
                # when connecting or a later tool fails. HTTP-only work opens no browser.
                self.stack.callback(self._release_remote)
                self.remaining()
                self._watch()
                pw = self.stack.enter_context(sync_playwright())
                self.browser = pw.chromium.connect_over_cdp(
                    self.session.connect_url, timeout=budget.NAVIGATION_MS
                )
                self.stack.callback(self.browser.close)
                self.browser.contexts[0].set_default_timeout(budget.ACTION_MS)
                self.browser.contexts[0].set_default_navigation_timeout(budget.NAVIGATION_MS)
                self.page = self.browser.contexts[0].pages[0]
            self.remaining()
        except Exception as exc:
            self.stopped = (
                str(exc)
                if isinstance(exc, budget.BrowserLimit)
                else "browser_connection_failed: no automatic replacement"
            )
            if self.session:
                exc.simbrief_session = f"https://www.browserbase.com/sessions/{self.session.id}"
            raise
        return self

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.timer:
                self.timer.cancel()
            future = self.pool.submit(copy_context().run, self.stack.close) if self.used else None
        try:
            if future:
                future.result(timeout=budget.CLEANUP_SECONDS)
        except Exception as exc:
            observability.event(
                "browserbase",
                session_id=self.session.id if self.session else None,
                cleanup_error=type(exc).__name__,
            )
            log.warning("SimBrief browser cleanup failed: %s", type(exc).__name__)
        finally:
            # The owner thread may be stuck in CDP. Release remotely without waiting for it.
            if self.lease and not self.release_attempted:
                self.abort("browser_cleanup: releasing remaining session")
            if self.lease:
                # Keep account ownership through latest-OFP retrieval, even if the idle
                # watchdog already ended the browser. Ambiguous releases stay fenced.
                try:
                    self.lease.finish(self.release_confirmed)
                except Exception as exc:
                    log.warning("SimBrief lease cleanup failed: %s", type(exc).__name__)
            self.pool.shutdown(wait=False)


@contextmanager
def session_scope():
    """Reuse a browser during active work; exit before waiting for approval or user input.

    Tool executor threads inherit this scope, and all browser operations run serially on
    its owning thread. Nested scopes share it. Standalone calls open and close their own scope.
    """
    current = _workflow_browser.get()
    if current is not None:
        yield current
        return
    current = _WorkflowBrowser()
    token = _workflow_browser.set(current)
    try:
        yield current
    finally:
        try:
            current.close()
        finally:
            _workflow_browser.reset(token)


def _browser_operation(call):
    @wraps(call)
    def wrapped(*args, **kwargs):
        with session_scope() as browser:
            return browser.run(call, *args, **kwargs)

    return wrapped


def _client() -> Browserbase:
    key = setting("BROWSERBASE_API_KEY")
    if not key:
        raise ValueError("missing_configuration: BROWSERBASE_API_KEY in .env")
    return Browserbase(api_key=key, timeout=budget.API_SECONDS, max_retries=0)


def _context_exists(bb: Browserbase, context_id: str) -> bool:
    try:
        bb.contexts.retrieve(context_id)
        return True
    except NotFoundError:
        return False


def _context_id(bb: Browserbase) -> str:
    """The configured profile, else the one this server last created, else a new one.

    Browserbase keeps a context until it is deleted. A new context starts signed out;
    ensure_logged_in signs it in on first use.
    """
    from ifdispatcher.core import open_store

    store = open_store()
    for candidate in (setting(CONTEXT_SETTING), store.read_setting(STORED_CONTEXT)):
        if candidate and _context_exists(bb, candidate):
            return candidate
    context = bb.contexts.create()
    store.save_setting(STORED_CONTEXT, context.id)
    return context.id


def open_session(bb: Browserbase, minutes: int = 15):
    # Cross-check provider state as well as the shared-store lease. This also fences a
    # session left by a prior process. Unrelated applications' sessions are never ended.
    context_id = _context_id(bb)
    active = [s for s in bb.sessions.list() if s.status not in budget.TERMINAL]
    if any(
        (s.user_metadata or {}).get("app") == "InfiniteFlightDispatcher"
        or s.context_id == context_id
        for s in active
    ):
        raise budget.BrowserLimit(
            "existing_browser_active: inspect or clean up the existing dispatcher session"
        )
    current = _workflow_browser.get()
    if current and current.lease:
        current.remaining()
        current.lease.fence_create()
    session = bb.sessions.create(
        browser_settings={
            "context": {"id": context_id, "persist": True},
            "viewport": {"width": 1440, "height": 900},
        },
        keep_alive=False,
        api_timeout=max(60, min(int(minutes * 60), budget.SESSION_SECONDS)),
        user_metadata={"app": "InfiniteFlightDispatcher", "managed_by": "browser_budget_v1"},
    )
    observability.browser_opened(session.id)
    return session


def release(bb: Browserbase, session_id: str) -> bool:
    """End the session; Browserbase persists the context's cookies on release."""
    # With keep_alive=False, disconnecting CDP may already have completed it.
    result = bb.sessions.retrieve(session_id)
    requested = result.status not in budget.TERMINAL
    if requested:
        result = bb.sessions.update(session_id, status="REQUEST_RELEASE")
    confirmed = result.status in budget.TERMINAL
    if not confirmed:
        confirmed = bb.sessions.retrieve(session_id).status in budget.TERMINAL
    observability.browser_closed(session_id, confirmed=confirmed, requested=requested)
    return confirmed


def session_inventory(cleanup: bool = False) -> dict:
    """Inspect sessions, optionally releasing only aged dispatcher-owned browsers.

    This never opens a browser. A release request is distinguished from confirmed completion.
    """
    from datetime import datetime, timezone

    bb = _client()
    now = datetime.now(timezone.utc)
    sessions = []
    for item in bb.sessions.list():
        if item.status in budget.TERMINAL:
            continue
        owned = (item.user_metadata or {}).get("app") == "InfiniteFlightDispatcher"
        started = item.started_at or item.created_at
        age = max(0, (now - started).total_seconds())
        row = {"id": item.id, "status": item.status, "managed": owned, "elapsed_s": round(age, 1)}
        if cleanup and owned and age >= budget.SESSION_SECONDS:
            # Recheck immediately before ending it; never act on unrelated applications.
            latest = bb.sessions.retrieve(item.id)
            if (
                latest.status not in budget.TERMINAL
                and (latest.user_metadata or {}).get("app") == "InfiniteFlightDispatcher"
            ):
                row.update(release_requested=True, released=release(bb, item.id))
        sessions.append(row)
    return {"admission": budget.admission_status(), "sessions": sessions}


@_browser_operation
def airframes(aircraft: str) -> dict:
    """Read actual selectable SimBrief profiles; does not generate a plan."""
    page = _workflow_browser.get().connect(minutes=15).page
    if not ensure_logged_in(page):
        return {"status": "not_logged_in"}
    page.select_option("#basetype", aircraft)
    page.wait_for_function("a => document.querySelector('#type').value === a", arg=aircraft)
    options = page.locator("#type").evaluate(
        "e => [...e.options].filter(o => o.value && !o.value.startsWith('--')).map(o => ({id:o.value, name:o.textContent.trim()}))"
    )
    return {
        "status": "ok",
        "aircraft": aircraft,
        "airframes": options,
        "note": "Selectable profiles only; simulator configuration and thrust applicability remain separate.",
    }


def _logged_in(page) -> bool:
    """True when the dispatch form (origin field) renders, i.e. the profile is signed in."""
    page.goto(DISPATCH_URL, wait_until="domcontentloaded", timeout=budget.NAVIGATION_MS)
    try:
        page.wait_for_selector("[name*=orig]", timeout=20_000)
        return True
    except Exception:
        return False


def _sign_in(page) -> bool:
    """Sign in through Navigraph's email/password form, if credentials are configured.

    Returns False without raising when there are no credentials, the password is refused, or
    Navigraph asks for something else (MFA, a new prompt): the page then stays on Navigraph.
    """
    username, password = setting("NAVIGRAPH_USERNAME"), setting("NAVIGRAPH_PASSWORD")
    if not (username and password):
        return False
    page.goto(DISPATCH_URL, wait_until="domcontentloaded", timeout=budget.NAVIGATION_MS)
    try:  # the cookie banner can appear after load and would block the Sign In click
        page.locator("#cookie-settings").get_by_text("Accept all cookies", exact=True).first.click(
            timeout=8_000
        )
    except Exception:
        pass  # no banner (already accepted in this profile)
    page.click("#login-button")
    page.wait_for_url(NAVIGRAPH_LOGIN, timeout=budget.NAVIGATION_MS)
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#login-id")
    try:
        page.wait_for_url(SIMBRIEF, timeout=budget.NAVIGATION_MS)
    except Exception:
        return False
    return _logged_in(page)


def ensure_logged_in(page) -> bool:
    """True when SimBrief's dispatch form is available, signing in first if needed."""
    return _logged_in(page) or _sign_in(page)


@_browser_operation
def keepalive() -> dict[str, Any]:
    """Refresh the saved SimBrief login (daily): open the profile, sign in if it lapsed, save."""
    browser = _workflow_browser.get().connect(minutes=15)
    ok = ensure_logged_in(browser.page)
    return {
        "status": "logged_in" if ok else "not_logged_in",
        "session": f"https://www.browserbase.com/sessions/{browser.session.id}",
    }


@_browser_operation
def login(minutes: int = 3) -> None:
    """Open a cloud browser on the persistent profile; the user logs into SimBrief there.

    Watches the user's tab without navigating it; once SimBrief no longer asks to sign in,
    confirms in a second tab that the dispatch page is available, then saves the profile.
    """
    minutes = min(minutes, budget.SESSION_SECONDS / 60)
    connection = _workflow_browser.get().connect(minutes=minutes)
    bb, session = connection.bb, connection.session
    live = bb.sessions.debug(session.id).debugger_fullscreen_url
    ok = False
    context = connection.browser.contexts[0]
    page = context.pages[0]
    page.goto(DISPATCH_URL, wait_until="domcontentloaded", timeout=budget.NAVIGATION_MS)
    print(f"Session: https://www.browserbase.com/sessions/{session.id}")
    print("LIVE VIEW (open and log into SimBrief/Navigraph):", live, flush=True)
    deadline = time.monotonic() + minutes * 60
    while time.monotonic() < deadline and not ok:
        page.wait_for_timeout(5_000)
        try:
            current = context.pages[-1]
            head = current.inner_text("body")[:3000].lower()
        except Exception:  # page mid-navigation during the user's login
            continue
        if "simbrief.com" in current.url and "sign in" not in head and "log in" not in head:
            ok = _logged_in(context.new_page())

    print("Logged in: profile saved." if ok else "Login not detected before timeout; run again.")
    sys.exit(0 if ok else 1)


@_browser_operation
def inspect_form() -> dict[str, Any]:
    """Developer aid: list the dispatch form's controls (names, types, options, labels)."""
    connection = _workflow_browser.get().connect(minutes=15)
    page = connection.page
    if not ensure_logged_in(page):
        return {"status": "not_logged_in"}
    fields = page.evaluate(
        """() => [...document.querySelectorAll('input, select, textarea, button')]
        .filter(e => e.offsetParent !== null || e.type === 'hidden')
        .map(e => ({tag: e.tagName.toLowerCase(), type: e.type || null,
          name: e.name || null, id: e.id || null,
          label: (e.labels && e.labels[0] ? e.labels[0].innerText : e.placeholder ||
                  e.getAttribute('aria-label') || e.innerText || '').trim().slice(0, 60),
          value: e.type === 'password' ? null : (e.value || '').slice(0, 40),
          options: e.tagName === 'SELECT' ? [...e.options].slice(0, 8).map(o => o.value) : null}))"""
    )
    shot = Path("artifacts/private/simbrief-dispatch-form.png")
    shot.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(shot), full_page=True)
    return {"status": "ok", "url": DISPATCH_URL, "fields": fields, "screenshot": str(shot)}


SET_DATE_JS = """(iso) => { const $e = jQuery('#date'); const dp = $e.data('daterangepicker');
    const m = moment.utc(iso); dp.setStartDate(m); dp.setEndDate(m);
    $e.val(m.format(dp.locale.format)); $e.trigger('apply.daterangepicker', dp);
    $e[0].dispatchEvent(new Event('change', {bubbles: true})); return $e.val(); }"""
SET_CHECKBOX_JS = """([id, on]) => { const e = document.getElementById(id);
    if (e.checked !== on) { e.checked = on; e.dispatchEvent(new Event('change', {bubbles: true})); }
    return e.checked; }"""


VISIBLE_MODALS_JS = """() => [...document.querySelectorAll('[class*=modal], [role=dialog]')]
    .filter(e => e.offsetParent !== null && e.innerText.trim())
    .map(e => e.innerText.trim().replace(/\\s+/g, ' ').slice(0, 300))"""
# In-page prompts with a known safe answer; anything else stops the run for review.
KNOWN_PROMPTS = {"departure time has changed": "Yes"}


def _answer_known_prompts(page) -> list[str]:
    answered = []
    for _ in range(3):
        page.wait_for_timeout(800)
        dialogs = page.get_by_role("dialog").filter(visible=True).all()
        if not dialogs:
            break
        # Only answer the front dialog. A matching prompt behind another dialog must not
        # receive a click through it (observed during the release form check).
        _, dialog = max(
            enumerate(dialogs),
            key=lambda pair: (
                pair[1].evaluate("e => parseInt(getComputedStyle(e).zIndex) || 0"),
                pair[0],
            ),
        )
        text = dialog.inner_text().lower()
        match = next((k for k in KNOWN_PROMPTS if k in text), None)
        if not match:
            break
        dialog.get_by_role("button", name=KNOWN_PROMPTS[match], exact=True).click()
        answered.append(f"{match} -> {KNOWN_PROMPTS[match]}")
    return answered


def form_values(fields: dict[str, Any]) -> dict[str, str]:
    """SimBrief dispatch form values (by element id) for one prepared leg."""
    from datetime import datetime

    departure = datetime.fromisoformat(fields["departure_utc"].replace("Z", "+00:00"))
    values = {
        "airline": fields.get("airline") or "",
        "fltnum": fields.get("flight_number") or "",
        "callsign": fields.get("callsign") or "",
        "orig": fields["origin"],
        "dest": fields["destination"],
        "basetype": fields["aircraft"],
        "pounds": "1" if fields["units"] == "LBS" else "0",
        "flighttype": "g" if fields.get("callsign") and not fields.get("airline") else "s",
        "pax": "" if fields.get("passengers") is None else str(fields["passengers"]),
        "route": (fields.get("route") or "").strip(),
        "date": departure.strftime("%d %b %Y - %H:%M"),
    }
    return values


def form_mismatches(fields: dict, want: dict, got: dict) -> dict:
    """Unspecified routes are left to SimBrief; explicitly agreed fields must match."""
    expected = dict(want)
    if not (fields.get("route") or "").strip():
        expected.pop("route", None)
    for key in ("airframe_id", "runway"):
        if fields.get(key):
            expected[key] = fields[key]
    return {
        key: {"want": value, "got": got.get(key)}
        for key, value in expected.items()
        if str(got.get(key)).strip().upper() != str(value).strip().upper()
    }


@_browser_operation
def generate(
    fields: dict[str, Any],
    click: bool,
    shots_dir: Path,
    before_click: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Fill the dispatch form on the logged-in cloud browser; click Generate only if `click`.

    `before_click` runs immediately before the Generate click (callers record the attempt there,
    so a failure earlier leaves the leg retryable). Returns status "filled" (dry run),
    "generated", "error", "uncertain", "fill_mismatch", or "not_logged_in", with screenshots and
    the full session replay link.
    """
    require_paid_operations()  # Browserbase time; a click also writes to SimBrief
    want = form_values(fields)
    shots_dir.mkdir(parents=True, exist_ok=True)
    tag = fields["tag"]
    connection = _workflow_browser.get().connect(minutes=15)
    session, page = connection.session, connection.page
    replay = f"https://www.browserbase.com/sessions/{session.id}"
    dialogs: list[str] = []

    def on_dialog(dialog):
        dialogs.append(dialog.message)
        dialog.dismiss()

    try:
        page.on("dialog", on_dialog)
        if not ensure_logged_in(page):
            return {
                "status": "not_logged_in",
                "session": replay,
                "reason": "SimBrief sign-in failed: check NAVIGRAPH_USERNAME and "
                "NAVIGRAPH_PASSWORD, or sign in once with ifd-simbrief",
            }
        page.select_option("#basetype", want["basetype"])
        page.wait_for_function(
            "a => document.querySelector('#type').value === a", arg=want["basetype"]
        )
        if fields.get("airframe_id"):
            page.select_option("#type", fields["airframe_id"])
        page.select_option("#pounds", want["pounds"])
        page.select_option("#flighttype", want["flighttype"])
        for field in ("airline", "fltnum", "callsign", "orig", "dest", "pax"):
            page.fill(f"#{field}", want[field])
            page.dispatch_event(f"#{field}", "change")
        page.evaluate(SET_CHECKBOX_JS, ["tlr", True])
        page.evaluate(SET_DATE_JS, fields["departure_utc"])
        answered = _answer_known_prompts(page)
        open_prompts = page.evaluate(VISIBLE_MODALS_JS)
        # Accepting the departure-time prompt resets runway selection. Apply the
        # explicitly approved runway afterwards, then verify the final form.
        if fields.get("runway") and not open_prompts:
            page.wait_for_function(
                "r => [...document.querySelector('#origrwy').options].some(o => o.value === r)",
                arg=fields["runway"],
            )
            page.select_option("#origrwy", fields["runway"])
        if not open_prompts:
            # Airport/date/runway lookups can replace the route asynchronously.
            # Finish those first, then apply the approved route. Without an agreed route
            # the form goes straight to Generate Flight: SimBrief chooses the route itself.
            # Route Finder is never clicked; it hung past its wait on oceanic legs.
            page.wait_for_function("() => jQuery.active === 0", timeout=30_000)
            open_prompts = page.evaluate(VISIBLE_MODALS_JS)
            if not open_prompts and want["route"]:
                page.fill("#route", want["route"])
                open_prompts = page.evaluate(VISIBLE_MODALS_JS)
        got = {k: page.input_value(f"#{k}") for k in want}
        got["tlr"] = page.evaluate("() => document.getElementById('tlr').checked")
        got.update(airframe_id=page.input_value("#type"), runway=page.input_value("#origrwy"))
        mismatched = form_mismatches(fields, want, got)
        if not got["tlr"]:
            mismatched["tlr"] = {"want": True, "got": False}
        filled_shot = shots_dir / f"{tag}-filled.png"
        page.screenshot(path=str(filled_shot), full_page=True)
        result: dict[str, Any] = {
            "session": replay,
            "values": got,
            "prompts_answered": answered,
            "screenshots": [str(filled_shot)],
        }
        if open_prompts or dialogs:
            return {**result, "status": "needs_review", "prompts": open_prompts + dialogs}
        if mismatched:
            return {**result, "status": "fill_mismatch", "mismatched": mismatched}
        if not click:
            return {**result, "status": "filled"}
        if before_click:
            before_click()
        page.get_by_text("Generate Flight", exact=True).click()
        status = "uncertain"
        prompts: list[str] = []
        for _ in range(60):  # up to ~2 minutes
            page.wait_for_timeout(2_000)
            if dialogs:
                status = "error"
                break
            if "/options/custom" not in page.url:
                status = "generated"
                break
            prompts = [
                t
                for t in page.evaluate(VISIBLE_MODALS_JS)
                if not any(w in t.lower() for w in ("generating", "loading", "please wait"))
            ]
            if prompts:  # unknown confirmation after Generate: never click through it
                status = "needs_review"
                break
        done_shot = shots_dir / f"{tag}-after.png"
        page.screenshot(path=str(done_shot))
        return {
            **result,
            "status": status,
            "final_url": page.url,
            "dialogs": dialogs,
            "prompts": prompts,
            "screenshots": [str(filled_shot), str(done_shot)],
        }
    except Exception as exc:
        exc.simbrief_session = replay
        raise
    finally:
        page.remove_listener("dialog", on_dialog)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] in ("sessions", "cleanup"):
        print(json.dumps(session_inventory(cleanup=sys.argv[1] == "cleanup"), indent=1))
    elif len(sys.argv) > 1 and sys.argv[1] == "inspect":
        print(json.dumps(inspect_form(), indent=1))
    else:
        login()
