"""SimBrief preparation, user-triggered retrieval, and immutable local snapshots."""

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
Airport = Annotated[str, Field(pattern=r"^[A-Z0-9]{4}$")]
Aircraft = Annotated[str, Field(pattern=r"^(?:[A-Z0-9]{2,4}|[0-9]+_[0-9]+)$")]


class Dispatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    trip: Identifier
    leg: Identifier
    revision: Annotated[int, Field(ge=1, strict=True)]
    origin: Airport | None = None
    destination: Airport | None = None
    aircraft: Aircraft | None = None
    departure: AwareDatetime | None = None
    units: Literal["KGS", "LBS"] | None = None
    passengers: Annotated[int, Field(ge=0, strict=True)] | None = None
    route: Annotated[str, Field(max_length=10000)] | None = None
    runway: Annotated[str, Field(pattern=r"^[0-3][0-9][LCR]?$", max_length=3)] | None = None
    airframe_id: Annotated[str, Field(pattern=r"^(?:[A-Z0-9]{2,4}|[0-9]+_[0-9]+)$")] | None = None
    configuration: Annotated[str, Field(max_length=200)] | None = None
    simulator_capacity: Annotated[float, Field(gt=0, le=1000000)] | None = None
    capacity_source: Annotated[str, Field(max_length=500)] | None = None
    arrival_target_utc: AwareDatetime | None = None


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def normalize(raw: bytes) -> dict:
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("malformed_response: expected JSON") from exc
    if not isinstance(obj, dict):
        raise ValueError("malformed_response: expected object")
    fetch = obj.get("fetch")
    if not isinstance(fetch, dict) or fetch.get("status") != "Success":
        raise ValueError("provider_error: no successful OFP response")
    for section in ("params", "aircraft", "origin", "destination"):
        if not isinstance(obj.get(section), dict):
            raise ValueError(f"malformed_response: missing {section}")
    if obj["params"].get("units") not in ("kgs", "lbs"):
        raise ValueError("unsupported_units: expected explicit kgs or lbs")
    tlr = obj.get("tlr")
    takeoff = tlr.get("takeoff") if isinstance(tlr, dict) else None
    conditions = takeoff.get("conditions") if isinstance(takeoff, dict) else None
    runways = takeoff.get("runway") if isinstance(takeoff, dict) else None
    selected = None
    status = "unavailable"
    if isinstance(conditions, dict) and isinstance(runways, list):
        if not all(isinstance(r, dict) for r in runways):
            raise ValueError("malformed_response: runway entries must be objects")
        matches = [r for r in runways if r.get("identifier") == conditions.get("planned_runway")]
        if len(matches) > 1:
            raise ValueError("malformed_response: ambiguous selected runway")
        if matches:
            selected, status = matches[0], "available"
    target = selected.get("thrust_value") if selected else None
    indication = selected.get("thrust_value_id") if selected else None
    general = obj.get("general")
    route = general.get("route") if isinstance(general, dict) else None
    return {
        "aircraft": {k: obj["aircraft"].get(k) for k in ("icao_code", "name", "engines")},
        "origin": obj["origin"].get("icao_code"),
        "destination": obj["destination"].get("icao_code"),
        "flight_route": route if isinstance(route, str) else None,
        "generated_at": obj["params"].get("time_generated"),
        "weight_units": obj["params"]["units"],
        "takeoff_status": status,
        "selected_takeoff": selected,
        "tlr": tlr,
        "target_status": "reported_unverified"
        if target not in (None, "", []) and indication not in (None, "", [])
        else "unavailable",
    }


class Store:
    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        self.path = directory / "dispatch.sqlite3"
        # Create with restrictive permissions before SQLite opens the file.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS requests (trip, leg, revision, payload, "
                "PRIMARY KEY(trip,leg,revision))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS snapshots (trip, leg, revision, raw BLOB, "
                "sha256, normalized, retrieved_at, PRIMARY KEY(trip,leg,revision))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS leg_meta (trip, leg, revision, payload, "
                "PRIMARY KEY(trip,leg,revision))"
            )
            db.execute("CREATE TABLE IF NOT EXISTS settings (name PRIMARY KEY, value)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def prepare(self, request: Dispatch):
        data = request.model_dump(mode="json")
        missing = [
            k
            for k in ("origin", "destination", "aircraft", "departure", "units")
            if data[k] is None
        ]
        if request.origin and request.origin == request.destination:
            raise ValueError("invalid_route: origin and destination must differ")
        if missing:
            return {"status": "missing_input", "missing_inputs": missing, "inputs": data}
        payload = encode(data)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT payload FROM requests WHERE trip=? AND leg=? AND revision=?",
                (request.trip, request.leg, request.revision),
            ).fetchone()
            if (
                old
                and encode(Dispatch.model_validate(json.loads(old[0])).model_dump(mode="json"))
                != payload
            ):
                raise ValueError("revision_conflict: use a new revision for changed inputs")
            db.execute(
                "INSERT OR IGNORE INTO requests VALUES (?,?,?,?)",
                (request.trip, request.leg, request.revision, payload),
            )
        return {
            "status": "prepared",
            "inputs": data,
            "fingerprint": digest(payload.encode()),
            "provider_defaults": "Unspecified options use SimBrief defaults; not submitted.",
            "generation": "blocked_developer_access",
        }

    def save(self, trip: str, leg: str, revision: int, raw: bytes, static_id: str | None):
        normalized = normalize(raw)
        obj = json.loads(raw)
        actual_static = obj["params"].get("static_id")
        if static_id and actual_static != static_id:
            raise ValueError("identity_mismatch: returned static ID differs")
        sha = digest(raw)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM requests WHERE trip=? AND leg=? AND revision=?",
                (trip, leg, revision),
            ).fetchone()
            if not row:
                raise ValueError("missing_request: prepare this leg/revision first")
            expected = json.loads(row[0])
            for key in ("origin", "destination"):
                if normalized[key] != expected[key]:
                    raise ValueError(f"identity_mismatch: {key} differs")
            if "_" in expected["aircraft"]:
                raise ValueError("unverified_custom_airframe: exact mapping not established")
            if normalized["aircraft"]["icao_code"] != expected["aircraft"]:
                raise ValueError("identity_mismatch: aircraft differs")
            if (
                expected.get("airframe_id")
                and obj["aircraft"].get("internal_id") != expected["airframe_id"]
            ):
                raise ValueError("identity_mismatch: selected SimBrief airframe differs")
            if normalized["weight_units"].upper() != expected["units"]:
                raise ValueError("identity_mismatch: units differ")
            meta_row = db.execute(
                "SELECT payload FROM leg_meta WHERE trip=? AND leg=? AND revision=?",
                (trip, leg, revision),
            ).fetchone()
            meta = json.loads(meta_row[0]) if meta_row else {}
            readback = ((meta.get("generation") or {}).get("values") or {}).get("route")
            route = (expected.get("route") or "").strip() or readback
            if route and " ".join(route.upper().split()) != " ".join(
                (normalized["flight_route"] or "").upper().split()
            ):
                raise ValueError(
                    "identity_mismatch: route differs from approved input or form readback"
                )
            if expected["runway"]:
                selected = normalized["selected_takeoff"]
                if not selected or selected.get("identifier") != expected["runway"]:
                    raise ValueError("identity_mismatch: runway differs")
            old = db.execute(
                "SELECT sha256 FROM snapshots WHERE trip=? AND leg=? AND revision=?",
                (trip, leg, revision),
            ).fetchone()
            if old and old[0] != sha:
                raise ValueError("revision_conflict: snapshot immutable; use a new revision")
            db.execute(
                "INSERT OR IGNORE INTO snapshots VALUES (?,?,?,?,?,?,?)",
                (
                    trip,
                    leg,
                    revision,
                    raw,
                    sha,
                    encode(normalized),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return self.read(trip, leg, revision)

    def save_meta(self, trip: str, leg: str, revision: int, meta: dict):
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO leg_meta VALUES (?,?,?,?)",
                (trip, leg, revision, encode(meta)),
            )

    def read_meta(self, trip: str, leg: str, revision: int) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM leg_meta WHERE trip=? AND leg=? AND revision=?",
                (trip, leg, revision),
            ).fetchone()
        return json.loads(row[0]) if row else {}

    def claim_generation(self, trip: str, leg: str, revision: int) -> dict | None:
        """Atomically claim the Generate click, including across conversation threads/restarts."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT payload FROM leg_meta WHERE trip=? AND leg=? AND revision=?",
                (trip, leg, revision),
            ).fetchone()
            meta = json.loads(row[0]) if row else {}
            previous = meta.get("generation") or {}
            if (
                meta.get("cancelled")
                or previous.get("at")
                or previous.get("status")
                in (
                    "generated",
                    "uncertain",
                    "clicking",
                )
            ):
                return None
            meta["generation"] = {
                "status": "clicking",
                "at": datetime.now(timezone.utc).isoformat(),
            }
            db.execute(
                "INSERT OR REPLACE INTO leg_meta VALUES (?,?,?,?)",
                (trip, leg, revision, encode(meta)),
            )
            return meta

    def save_setting(self, name: str, value: str):
        """Server-owned state that must outlive the container (e.g. a recreated browser profile)."""
        with self.connect() as db:
            db.execute(
                "INSERT INTO settings VALUES (?,?) "
                "ON CONFLICT (name) DO UPDATE SET value = excluded.value",
                (name, value),
            )

    def read_setting(self, name: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT value FROM settings WHERE name=?", (name,)).fetchone()
        return row[0] if row else None

    def trip_legs(self, trip: str) -> list[tuple[str, dict, dict]]:
        """Each dispatched leg of a trip at its latest revision: (leg, request, meta)."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT r.leg, r.payload, m.payload FROM requests r LEFT JOIN leg_meta m "
                "ON m.trip = r.trip AND m.leg = r.leg AND m.revision = r.revision "
                "WHERE r.trip=? ORDER BY r.leg, r.revision",
                (trip,),
            ).fetchall()
        latest = {
            leg: (json.loads(request), json.loads(meta or "{}")) for leg, request, meta in rows
        }
        return sorted(
            [(leg, request, meta) for leg, (request, meta) in latest.items()],
            key=lambda item: (
                not item[0].isdigit(),
                int(item[0]) if item[0].isdigit() else item[0],
            ),
        )

    def trips(self) -> list[str]:
        with self.connect() as db:
            return [
                r[0]
                for r in db.execute("SELECT DISTINCT trip FROM requests ORDER BY trip").fetchall()
            ]

    def revisions(self, trip: str, leg: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload FROM requests WHERE trip=? AND leg=? ORDER BY revision", (trip, leg)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def read_request(self, trip: str, leg: str, revision: int) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM requests WHERE trip=? AND leg=? AND revision=?",
                (trip, leg, revision),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def read_raw(self, trip: str, leg: str, revision: int) -> dict:
        with self.connect() as db:
            row = db.execute(
                "SELECT raw FROM snapshots WHERE trip=? AND leg=? AND revision=?",
                (trip, leg, revision),
            ).fetchone()
        if not row:
            raise ValueError("missing_snapshot: no saved plan for this leg revision")
        return json.loads(row[0])

    def read(self, trip, leg, revision):
        with self.connect() as db:
            row = db.execute(
                "SELECT sha256, normalized, retrieved_at FROM snapshots "
                "WHERE trip=? AND leg=? AND revision=?",
                (trip, leg, revision),
            ).fetchone()
        if not row:
            raise ValueError("missing_snapshot: explicitly retrieve this prepared revision first")
        return {
            "status": "saved",
            "trip": trip,
            "leg": leg,
            "revision": revision,
            "raw_sha256": row[0],
            "data": json.loads(row[1]),
            "retrieved_at": row[2],
            "correlation": "route_aircraft_units_checked; generation_not_verified",
        }


PG_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS requests (trip TEXT, leg TEXT, revision INTEGER, payload TEXT, "
    "PRIMARY KEY (trip, leg, revision))",
    "CREATE TABLE IF NOT EXISTS snapshots (trip TEXT, leg TEXT, revision INTEGER, raw BYTEA, "
    "sha256 TEXT, normalized TEXT, retrieved_at TEXT, PRIMARY KEY (trip, leg, revision))",
    "CREATE TABLE IF NOT EXISTS leg_meta (trip TEXT, leg TEXT, revision INTEGER, payload TEXT, "
    "PRIMARY KEY (trip, leg, revision))",
    "CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT)",
)
LOCK_ID = 4242  # serializes Store writes, like SQLite's BEGIN IMMEDIATE


def _pg_sql(sql: str) -> str:
    """Translate the Store's SQLite statements to Postgres."""
    if sql == "BEGIN IMMEDIATE":
        return f"SELECT pg_advisory_xact_lock({LOCK_ID})"
    sql = sql.replace("?", "%s")
    if sql.startswith("INSERT OR IGNORE INTO"):
        return sql.replace("INSERT OR IGNORE INTO", "INSERT INTO", 1) + " ON CONFLICT DO NOTHING"
    if sql.startswith("INSERT OR REPLACE INTO"):
        return (
            sql.replace("INSERT OR REPLACE INTO", "INSERT INTO", 1)
            + " ON CONFLICT (trip, leg, revision) DO UPDATE SET payload = EXCLUDED.payload"
        )
    return sql


class _PgConnection:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql: str, params=()):
        return self.conn.execute(_pg_sql(sql), params)


class PgStore(Store):
    """Store on Postgres (Neon) for the deployed service; same logic as the SQLite Store."""

    def __init__(self, dsn: str):
        self.dsn = dsn
        with self.connect() as db:
            for ddl in PG_SCHEMA:
                db.conn.execute(ddl)

    @contextmanager
    def connect(self):
        import psycopg

        # prepare_threshold=None: no server-side prepared statements (Neon's pooler).
        with psycopg.connect(self.dsn, prepare_threshold=None) as conn:
            yield _PgConnection(conn)


def open_store() -> Store:
    """Postgres when DATABASE_URL is set (deployment), else the local SQLite store."""
    from ifdispatcher.config import data_dir, setting

    dsn = setting("DATABASE_URL")
    return PgStore(dsn) if dsn else Store(data_dir())


FETCHER = "https://www.simbrief.com/api/xml.fetcher.php"


def _fetch_params(alias: str | None, static_id: str | None, userid: str | None) -> dict:
    if not alias and not userid:
        raise ValueError("missing_configuration: set SIMBRIEF_ALIAS or SIMBRIEF_USERID")
    params = {"client": "InfiniteFlightDispatcher_0_1", "json": "v2"}
    params.update({"username": alias} if alias else {"userid": userid})
    if static_id:
        params["static_id"] = static_id
    return params


def _checked(response: httpx.Response) -> bytes:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"http_error: {exc.response.status_code}; no retry performed") from exc
    normalize(response.content)
    return response.content


async def fetch(
    alias: str | None, static_id: str | None = None, transport=None, userid: str | None = None
) -> bytes:
    params = _fetch_params(alias, static_id, userid)
    try:
        async with httpx.AsyncClient(timeout=30, transport=transport) as client:
            response = await client.get(FETCHER, params=params)
    except httpx.RequestError as exc:
        raise ValueError("network_error: retrieval failed; no retry performed") from exc
    return _checked(response)


def fetch_sync(
    alias: str | None, static_id: str | None = None, transport=None, userid: str | None = None
) -> bytes:
    """One user-triggered latest-plan fetch (no polling), for synchronous agent tools."""
    params = _fetch_params(alias, static_id, userid)
    try:
        with httpx.Client(timeout=30, transport=transport) as client:
            response = client.get(FETCHER, params=params)
    except httpx.RequestError as exc:
        raise ValueError("network_error: retrieval failed; no retry performed") from exc
    return _checked(response)
