"""SimBrief data entry on a Browserbase cloud browser with a persistent logged-in profile.

The user logs into SimBrief once through the Browserbase live view (credentials and MFA never
pass through this code); the context persists cookies for later sessions. Generation is an
external write: callers must have the user's approval, fill once, verify the fields, and click
Generate at most once per approved dispatch.
"""

import json
import os
import time
import sys
from pathlib import Path
from typing import Any

from browserbase import Browserbase
from playwright.sync_api import sync_playwright

from ifdispatcher.config import ENV_FILE, setting

HOME_URL = "https://www.simbrief.com/home/"
DISPATCH_URL = "https://dispatch.simbrief.com/options/custom"
CONTEXT_SETTING = "BROWSERBASE_SIMBRIEF_CONTEXT_ID"


def _client() -> Browserbase:
    key = setting("BROWSERBASE_API_KEY")
    if not key:
        raise ValueError("missing_configuration: BROWSERBASE_API_KEY in .env")
    return Browserbase(api_key=key)  # the key identifies the project


def _context_id(bb: Browserbase) -> str:
    existing = setting(CONTEXT_SETTING)
    if existing:
        return existing
    context = bb.contexts.create()
    with open(ENV_FILE, "a") as handle:  # context id is an identifier, not a secret
        handle.write(f"{CONTEXT_SETTING}={context.id}\n")
    os.chmod(ENV_FILE, 0o600)
    return context.id


def open_session(bb: Browserbase, minutes: int = 15):
    return bb.sessions.create(
        browser_settings={
            "context": {"id": _context_id(bb), "persist": True},
            "viewport": {"width": 1440, "height": 900},
        },
        keep_alive=True,
        api_timeout=minutes * 60,
        user_metadata={"app": "InfiniteFlightDispatcher"},
    )


def release(bb: Browserbase, session_id: str) -> None:
    """End the session; Browserbase persists the context's cookies on release."""
    bb.sessions.update(session_id, status="REQUEST_RELEASE")


def _logged_in(page) -> bool:
    """True when the dispatch form (origin field) renders, i.e. the profile is signed in."""
    page.goto(DISPATCH_URL, wait_until="domcontentloaded", timeout=60_000)
    try:
        page.wait_for_selector("[name*=orig]", timeout=20_000)
        return True
    except Exception:
        return False


def login(minutes: int = 15) -> None:
    """Open a cloud browser on the persistent profile; the user logs into SimBrief there.

    Watches the user's tab without navigating it; once SimBrief no longer asks to sign in,
    confirms in a second tab that the dispatch page is available, then saves the profile.
    """
    bb = _client()
    session = open_session(bb, minutes=minutes + 5)
    live = bb.sessions.debug(session.id).debugger_fullscreen_url
    ok = False
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(session.connect_url)
            context = browser.contexts[0]
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
            browser.close()
    finally:
        release(bb, session.id)
    print("Logged in: profile saved." if ok else "Login not detected before timeout; run again.")
    sys.exit(0 if ok else 1)


def inspect_form() -> dict[str, Any]:
    """Developer aid: list the dispatch form's controls (names, types, options, labels)."""
    bb = _client()
    session = open_session(bb)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(session.connect_url)
            page = browser.contexts[0].pages[0]
            if not _logged_in(page):
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
            browser.close()
            return {"status": "ok", "url": DISPATCH_URL, "fields": fields, "screenshot": str(shot)}
    finally:
        release(bb, session.id)


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
        texts = page.evaluate(VISIBLE_MODALS_JS)
        match = next((k for k in KNOWN_PROMPTS for t in texts if k in t.lower()), None)
        if not match:
            break
        dialog = page.locator("[class*=modal], [role=dialog]").filter(has_text=match).last
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
        "route": "",
        "date": departure.strftime("%d %b %Y - %H:%M"),
    }
    return values


def generate(fields: dict[str, Any], click: bool, shots_dir: Path) -> dict[str, Any]:
    """Fill the dispatch form on the logged-in cloud browser; click Generate only if `click`.

    Returns status "filled" (dry run), "generated", "error", "uncertain", "fill_mismatch", or
    "not_logged_in", with screenshots and the full session replay link.
    """
    want = form_values(fields)
    shots_dir.mkdir(parents=True, exist_ok=True)
    tag = fields["tag"]
    bb = _client()
    session = open_session(bb, minutes=10)
    replay = f"https://www.browserbase.com/sessions/{session.id}"
    dialogs: list[str] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(session.connect_url)
            page = browser.contexts[0].pages[0]
            page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
            if not _logged_in(page):
                return {"status": "not_logged_in", "session": replay}
            page.select_option("#basetype", want["basetype"])
            page.wait_for_function(
                "a => document.querySelector('#type').value === a", arg=want["basetype"]
            )
            page.select_option("#pounds", want["pounds"])
            page.select_option("#flighttype", want["flighttype"])
            for field in ("airline", "fltnum", "callsign", "orig", "dest", "pax"):
                page.fill(f"#{field}", want[field])
                page.dispatch_event(f"#{field}", "change")
            page.fill("#route", "")
            page.evaluate(SET_CHECKBOX_JS, ["tlr", True])
            page.evaluate(SET_DATE_JS, fields["departure_utc"])
            answered = _answer_known_prompts(page)
            open_prompts = page.evaluate(VISIBLE_MODALS_JS)
            got = {k: page.input_value(f"#{k}") for k in want}
            got["tlr"] = page.evaluate("() => document.getElementById('tlr').checked")
            mismatched = {
                k: {"want": want[k], "got": got[k]}
                for k in want
                if str(got[k]).strip().upper() != str(want[k]).strip().upper()
            }
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
            if mismatched:
                return {**result, "status": "fill_mismatch", "mismatched": mismatched}
            if open_prompts:
                return {**result, "status": "needs_review", "prompts": open_prompts}
            if not click:
                return {**result, "status": "filled"}
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
            browser.close()
            return {
                **result,
                "status": status,
                "final_url": page.url,
                "dialogs": dialogs,
                "prompts": prompts,
                "screenshots": [str(filled_shot), str(done_shot)],
            }
    finally:
        release(bb, session.id)


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "inspect":
        print(json.dumps(inspect_form(), indent=1))
    else:
        login()
