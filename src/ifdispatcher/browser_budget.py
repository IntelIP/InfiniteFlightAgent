"""Single-user browser admission, shared by processes using the same dispatcher store.

The existing transactional settings store supplies a bounded FIFO and an expiring lease.
No browser is opened while waiting. Unconfirmed release keeps the lease until the provider's
maximum lifetime has elapsed, including allowance for a delayed create response.
"""

import json
import time
import uuid

from ifdispatcher import observability
from ifdispatcher.core import open_store

SESSION_SECONDS = 180
IDLE_SECONDS = 30
QUEUE_SECONDS = 30
MAX_WAITERS = 2
API_SECONDS = 8
CLEANUP_SECONDS = 12
ACTION_MS = 10_000
NAVIGATION_MS = 20_000
KEY = "simbrief_browser_admission_v1"
TERMINAL = {"COMPLETED", "ERROR", "TIMED_OUT"}


class BrowserLimit(ValueError):
    """A bounded browser operation stopped; never automatically create a replacement."""


class Lease:
    def __init__(self):
        self.id = uuid.uuid4().hex
        self.store = open_store()

    def _change(self, action):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM settings WHERE name=?", (KEY,)).fetchone()
            state = json.loads(row[0]) if row else {"active": None, "waiting": []}
            now = time.time()
            if state["active"] and state["active"]["until"] <= now:
                state["active"] = None
            state["waiting"] = [w for w in state["waiting"] if w["until"] > now]
            result = action(state, now)
            db.execute(
                "INSERT INTO settings (name,value) VALUES (?,?) "
                "ON CONFLICT (name) DO UPDATE SET value=excluded.value",
                (KEY, json.dumps(state)),
            )
            return result

    def acquire(self):
        started = time.monotonic()

        def enqueue(state, now):
            if len(state["waiting"]) + int(state["active"] is not None) >= MAX_WAITERS + 1:
                raise BrowserLimit("browser_queue_full: two workflows already waiting")
            state["waiting"].append({"id": self.id, "until": now + QUEUE_SECONDS})

        self._change(enqueue)
        try:
            while True:

                def claim(state, now):
                    if (
                        not state["active"]
                        and state["waiting"]
                        and state["waiting"][0]["id"] == self.id
                    ):
                        state["waiting"].pop(0)
                        state["active"] = {
                            "id": self.id,
                            "phase": "active_workflow",
                            "until": now + SESSION_SECONDS + API_SECONDS * 3 + CLEANUP_SECONDS,
                        }
                        return True
                    return False

                if self._change(claim):
                    observability.event(
                        "browserbase_admission", queue_wait_s=round(time.monotonic() - started, 3)
                    )
                    return
                if time.monotonic() - started >= QUEUE_SECONDS:
                    raise BrowserLimit("browser_queue_timeout: no browser opened; try later")
                time.sleep(0.1)
        except BaseException:
            self._change(
                lambda s, _: s.update(waiting=[w for w in s["waiting"] if w["id"] != self.id])
            )
            raise

    def finish(self, confirmed):
        def remove(state, _):
            if state["active"] and state["active"]["id"] == self.id:
                if confirmed:
                    state["active"] = None
                else:
                    state["active"]["phase"] = "awaiting_provider_expiry"

        self._change(remove)

    def fence_create(self):
        def extend(state, now):
            if not state["active"] or state["active"]["id"] != self.id:
                raise BrowserLimit("browser_lease_lost: no session created")
            state["active"]["until"] = now + SESSION_SECONDS + API_SECONDS + CLEANUP_SECONDS

        self._change(extend)


def admission_status():
    lease = Lease()
    return lease._change(
        lambda s, now: {
            "active": int(s["active"] is not None),
            "waiting": len(s["waiting"]),
            "max_active": 1,
            "max_waiting": MAX_WAITERS,
            "session_seconds": SESSION_SECONDS,
            "idle_seconds": IDLE_SECONDS,
            "queue_seconds": QUEUE_SECONDS,
            "phase": s["active"].get("phase", "active_workflow") if s["active"] else "idle",
            "lease_expires_in_s": max(0, round(s["active"]["until"] - now)) if s["active"] else 0,
        }
    )
