"""Evaluation-only FlightAware replay/recording and a batch dollar ceiling.

Fixtures replace the HTTP boundary, keeping production filtering/normalization intact.
A missing fixture is an invalid evaluation, never permission for a network fallback.
"""

import copy
import json
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import RLock
from unittest.mock import patch

import httpx

from ifdispatcher import agent, flights, workflow


class FixtureMiss(ValueError):
    pass


class BudgetExceeded(ValueError):
    pass


def request_key(path, params):
    return path, tuple(sorted((k, str(v)) for k, v in (params or {}).items() if v is not None))


class FlightData:
    """One instance per sequential evaluation batch; thread-safe across tool calls."""

    def __init__(self, mode="replay", budget_usd="1.00"):
        if mode not in ("replay", "live"):
            raise ValueError("mode must be replay or live")
        amount = Decimal(str(budget_usd))
        if not amount.is_finite() or amount <= 0 or amount * 1000 != int(amount * 1000):
            raise ValueError("budget must be positive, finite, with at most three decimal places")
        self.mode = mode
        self.limit = int(amount * 1000)
        self.charged = 0
        self.held = 0
        self.lock = RLock()
        self.calls = []
        self.misses = []
        self.budget_blocked = False
        self.replay_hits = 0
        self.fixture_kind = None
        self.fixture_clock = None

    def report(self):
        return {
            "flight_data_mode": self.mode,
            "aeroapi_usd": self.charged / 1000,
            "aeroapi_held_usd": self.held / 1000,
            "aeroapi_budget_usd": self.limit / 1000 if self.mode == "live" else 0,
            "aeroapi_calls": copy.deepcopy(self.calls),
            "fixture_misses": list(self.misses),
            "replay_hits": self.replay_hits,
            "budget_blocked": self.budget_blocked,
        }

    @contextmanager
    def case(self, fixture: Path, *, clock=None):
        """Process-global patches: cases must run sequentially, as the runner does."""
        self.fixture_kind = None
        self.fixture_clock = None
        original_get = flights._get
        recordings = []
        start = clock or datetime.now(timezone.utc).isoformat()
        frozen = datetime.fromisoformat(start.replace("Z", "+00:00"))

        class FrozenDatetime(datetime):
            @classmethod
            def now(_cls, tz=None):
                return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)

        if self.mode == "replay":
            data = json.loads(fixture.read_text())
            if data.get("schema_version") != 1 or data.get("kind") not in (
                "recorded",
                "derived_recording",
                "synthetic",
            ):
                raise ValueError("invalid fixture schema/provenance kind")
            self.fixture_kind = data["kind"]
            self.fixture_clock = data["clock"]
            frozen = datetime.fromisoformat(data["clock"].replace("Z", "+00:00"))
            if frozen.tzinfo is None:
                raise ValueError("fixture clock must include timezone")
            entries = {}
            for row in data["requests"]:
                key = request_key(row["path"], row.get("params"))
                if key in entries and (entries[key]["body"], entries[key]["status_code"]) != (
                    row["body"],
                    row["status_code"],
                ):
                    raise ValueError(f"conflicting fixture requests: {key}")
                entries[key] = row

            def replay(path, params=None, transport=None):
                key = request_key(path, params)
                with self.lock:
                    row = entries.get(key)
                    if row is None:
                        message = f"fixture_miss: {path} {dict(key[1])}"
                        self.misses.append(message)
                        raise FixtureMiss(message)
                    self.replay_hits += 1
                status = row["status_code"]
                if status == 401:
                    raise ValueError(
                        "unauthorized: invalid key or endpoint above the Personal tier"
                    )
                if status == 429:
                    raise ValueError("rate_limited: AeroAPI rate limit; wait before retrying")
                if status >= 400:
                    raise ValueError(f"http_error: AeroAPI returned {status} (replayed)")
                return copy.deepcopy(row["body"])

            replacement = replay
        else:
            self.fixture_kind = "recorded"
            self.fixture_clock = start

            def live(path, params=None, transport=None):
                # Serialize reserve/send/settle, including simultaneous model tool calls.
                with self.lock:
                    query = {k: v for k, v in (params or {}).items() if v is not None}
                    cached = flights._airport_cached(path) if not query else None
                    if cached is not None:
                        flights.usage["cache_hits"] += 1
                        recordings.append(
                            dict(
                                path=path,
                                params=query,
                                status_code=200,
                                body=cached,
                                origin="airport_cache",
                            )
                        )
                        return cached

                    def send(request):
                        rate = flights.price_milliusd(path)  # Unknown endpoints fail closed.
                        pages = int(query.get("max_pages") or 1)
                        if not 1 <= pages <= flights.MAX_PAGES:
                            raise ValueError("invalid max_pages")
                        reserve = rate * pages
                        if self.charged + self.held + reserve > self.limit:
                            self.budget_blocked = True
                            raise BudgetExceeded("aeroapi_budget_exceeded: batch ceiling reached")
                        self.held += reserve
                        row = dict(
                            path=path,
                            params=query,
                            reserved_usd=reserve / 1000,
                            status_code=None,
                            result_sets=None,
                            cost_usd=None,
                        )
                        self.calls.append(row)
                        # Keep the reservation on transport or malformed-response failures.
                        with transport or httpx.HTTPTransport() as upstream:
                            response = upstream.handle_request(request)
                            response.read()
                        row["status_code"] = response.status_code
                        body = response.json()
                        recordings.append(
                            dict(
                                path=path, params=query, status_code=response.status_code, body=body
                            )
                        )
                        if response.status_code < 400:
                            actual_pages = max(1, int(body.get("num_pages") or 1))
                            row.update(
                                result_sets=actual_pages, cost_usd=rate * actual_pages / 1000
                            )
                            self.charged += rate * actual_pages
                            self.held -= reserve
                            if actual_pages > pages:
                                self.budget_blocked = True
                                raise BudgetExceeded("provider_exceeded_requested_page_limit")
                        # Non-success responses retain the conservative hold: no blind retry.
                        return response

                    before = len(recordings)
                    value = original_get(path, query, transport=httpx.MockTransport(send))
                    if len(recordings) == before:
                        recordings.append(
                            dict(
                                path=path,
                                params=query,
                                status_code=200,
                                body=value,
                                origin="memory_cache",
                            )
                        )
                    if not query:
                        flights._save_airport(path, value)
                    return value

            replacement = live
        flights._cache.clear()
        with ExitStack() as stack:
            stack.enter_context(patch.object(flights, "_get", replacement))
            for module in (agent, flights, workflow):
                stack.enter_context(patch.object(module, "datetime", FrozenDatetime))
            try:
                yield
            finally:
                if self.mode == "live":
                    fixture.parent.mkdir(parents=True, exist_ok=True)
                    fixture.write_text(
                        json.dumps(
                            {
                                "schema_version": 1,
                                "kind": "recorded",
                                "clock": start,
                                "provenance": {
                                    "description": "Live HTTP responses; cache origins labeled"
                                },
                                "requests": recordings,
                            },
                            indent=2,
                        )
                        + "\n"
                    )
                flights._cache.clear()
