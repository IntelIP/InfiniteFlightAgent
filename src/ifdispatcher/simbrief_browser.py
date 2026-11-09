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
from threading import Lock, get_ident
from typing import Any

from browserbase import Browserbase, NotFoundError
from playwright.sync_api import sync_playwright

from ifdispatcher.config import require_paid_operations, setting
from ifdispatcher import observability

HOME_URL = "https://www.simbrief.com/home/"
DISPATCH_URL = "https://dispatch.simbrief.com/options/custom"
CONTEXT_SETTING = "BROWSERBASE_SIMBRIEF_CONTEXT_ID"
STORED_CONTEXT = "browserbase_simbrief_context_id"  # store key for a context this server created
NAVIGRAPH_LOGIN = re.compile(r"identity\.api\.navigraph\.com")
SIMBRIEF = re.compile(r"simbrief\.com")
_workflow_browser = ContextVar("ifd_workflow_browser", default=None)
log = logging.getLogger(__name__)


class _WorkflowBrowser:
    """One lazy connection, owned by one thread because Playwright is thread-bound."""

    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="simbrief-browser")
        self.stack = ExitStack()
        self.lock = Lock()
        self.used = False
        self.closed = False
        self.session = None
        self.page = None
        self.owner = None

    def run(self, call, *args, **kwargs):
        if self.owner == get_ident():
            return call(*args, **kwargs)
        with self.lock:
            if self.closed:
                raise ValueError("SimBrief workflow browser is already closed")
            self.used = True
            future = self.pool.submit(copy_context().run, call, *args, **kwargs)
        return future.result()

    def connect(self, minutes):
        require_paid_operations()
        self.owner = get_ident()
        try:
            if self.session is not None and self.page is None:
                raise ValueError(
                    "SimBrief workflow browser could not connect; start a new workflow"
                )
            if self.session is None:
                self.bb = _client()
                self.session = open_session(self.bb, minutes=minutes)
                # LIFO cleanup: disconnect, stop Playwright, then release Browserbase even
                # when connecting or a later tool fails. HTTP-only work opens no browser.
                self.stack.callback(release, self.bb, self.session.id)
                pw = self.stack.enter_context(sync_playwright())
                self.browser = pw.chromium.connect_over_cdp(self.session.connect_url)
                self.stack.callback(self.browser.close)
                self.page = self.browser.contexts[0].pages[0]
        except Exception as exc:
            if self.session:
                exc.simbrief_session = f"https://www.browserbase.com/sessions/{self.session.id}"
            raise
        return self

    def close(self):
        with self.lock:
            self.closed = True
            future = self.pool.submit(copy_context().run, self.stack.close) if self.used else None
        try:
            if future:
                future.result()
        except Exception as exc:
            observability.event(
                "browserbase",
                session_id=self.session.id if self.session else None,
                cleanup_error=type(exc).__name__,
            )
            log.warning("SimBrief browser cleanup failed: %s", type(exc).__name__)
        finally:
            self.pool.shutdown(wait=True)


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
    return Browserbase(api_key=key)  # the key identifies the project


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
    session = bb.sessions.create(
        browser_settings={
            "context": {"id": _context_id(bb), "persist": True},
            "viewport": {"width": 1440, "height": 900},
        },
        keep_alive=True,
        api_timeout=minutes * 60,
        user_metadata={"app": "InfiniteFlightDispatcher"},
    )
    observability.browser_opened(session.id)
    return session


def release(bb: Browserbase, session_id: str) -> None:
    """End the session; Browserbase persists the context's cookies on release."""
    bb.sessions.update(session_id, status="REQUEST_RELEASE")
    observability.browser_closed(session_id)


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
    page.goto(DISPATCH_URL, wait_until="domcontentloaded", timeout=60_000)
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
    page.goto(DISPATCH_URL, wait_until="domcontentloaded", timeout=60_000)
    try:  # the cookie banner can appear after load and would block the Sign In click
        page.locator("#cookie-settings").get_by_text("Accept all cookies", exact=True).first.click(
            timeout=8_000
        )
    except Exception:
        pass  # no banner (already accepted in this profile)
    page.click("#login-button")
    page.wait_for_url(NAVIGRAPH_LOGIN, timeout=30_000)
    page.fill("#username", username)
    page.fill("#password", password)
    page.click("#login-id")
    try:
        page.wait_for_url(SIMBRIEF, timeout=60_000)
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
def login(minutes: int = 15) -> None:
    """Open a cloud browser on the persistent profile; the user logs into SimBrief there.

    Watches the user's tab without navigating it; once SimBrief no longer asks to sign in,
    confirms in a second tab that the dispatch page is available, then saves the profile.
    """
    connection = _workflow_browser.get().connect(minutes=minutes + 5)
    bb, session = connection.bb, connection.session
    live = bb.sessions.debug(session.id).debugger_fullscreen_url
    ok = False
    context = connection.browser.contexts[0]
    page = context.pages[0]
    page.goto(DISPATCH_URL, wait_until="domcontentloaded", timeout=60_000)
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
    """Unspecified routes use Route Finder; explicitly agreed fields must match."""
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
            # Finish those first, then apply the approved route or run Route Finder.
            page.wait_for_function("() => jQuery.active === 0", timeout=60_000)
            open_prompts = page.evaluate(VISIBLE_MODALS_JS)
            if not open_prompts:
                if want["route"]:
                    page.fill("#route", want["route"])
                else:
                    page.get_by_text("Find Route", exact=True).click()
                    page.wait_for_function("() => jQuery.active === 0", timeout=60_000)
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
        if not want["route"] and got["route"].strip().upper() in ("", "DCT", "DIRECT"):
            return {
                **result,
                "status": "needs_review",
                "reason": "Route Finder returned no waypoint routing. Supply a route or "
                "explicitly approve DCT before generating.",
            }
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
    if len(sys.argv) > 1 and sys.argv[1] == "inspect":
        print(json.dumps(inspect_form(), indent=1))
    else:
        login()
