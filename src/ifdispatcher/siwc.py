"""Sign in with ChatGPT (plan usage) for this locally run personal project.

Follows https://developers.openai.com/siwc/token-sharing-open-source (sign-in, sessions,
models-and-inference, preview limitations). Credentials live outside the repository in
~/.config/InfiniteFlightDispatcher/ with owner-only permissions and are never logged.
"""

import base64
import fcntl
import hashlib
import json
import os
import secrets
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import jwt
from langchain_openai import ChatOpenAI
from openai.types.responses import ResponseFunctionCallArgumentsDeltaEvent
from pydantic import model_validator

from ifdispatcher.config import setting

ISSUER = "https://auth.openai.com"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
SCOPES = "openid profile email offline_access resource.invoke chatgpt.tokens.use.direct"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
AGENT_NAME = "Infinite Flight Dispatcher"
CONFIG = Path.home() / ".config" / "InfiniteFlightDispatcher"
CREDENTIALS = CONFIG / "siwc.json"
HOST_ID = CONFIG / "host_id"
REFRESH_MARGIN = 120
# Preview: these Responses fields are rejected on the ChatGPT-plan route.
UNSUPPORTED = {
    "background",
    "conversation",
    "max_output_tokens",
    "max_tool_calls",
    "metadata",
    "moderation",
    "multi_agent",
    "prompt",
    "prompt_cache_retention",
    "safety_identifier",
    "temperature",
    "top_logprobs",
    "top_p",
    "truncation",
    "user",
    "previous_response_id",
}


def _write_private(path: Path, text: str) -> None:
    CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.replace(tmp, path)


def host_id() -> str:
    if HOST_ID.exists():
        return HOST_ID.read_text().strip()
    value = f"urn:uuid:{uuid.uuid4()}"
    _write_private(HOST_ID, value)
    return value


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _validate_id_token(id_token: str, client_id: str, nonce: str | None) -> dict:
    config = httpx.get(ISSUER + "/.well-known/openid-configuration", timeout=15).json()
    signing_key = jwt.PyJWKClient(config["jwks_uri"]).get_signing_key_from_jwt(id_token)
    claims = jwt.decode(
        id_token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience=client_id,
        issuer=config.get("issuer", ISSUER),
    )
    if nonce is not None and claims.get("nonce") != nonce:
        raise ValueError("siwc_error: ID token nonce mismatch")
    return claims


def _record(tokens: dict, client_id: str, claims: dict, host: str) -> dict:
    return {
        "email": claims.get("email"),
        "issuer": claims.get("iss"),
        "subject": claims.get("sub"),
        "client_id": client_id,
        "ext_agent_host_id": host,
        "id_token": tokens.get("id_token"),
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "token_type": tokens.get("token_type", "Bearer"),
        "expires_at": time.time() + int(tokens.get("expires_in", 3600)),
        "scopes": (tokens.get("scope") or "").split(),
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def _save(tokens: dict, client_id: str, claims: dict) -> dict:
    record = _record(tokens, client_id, claims, host_id())
    _write_private(CREDENTIALS, json.dumps(record, indent=2))
    return record


def _refreshed(record: dict) -> dict:
    """Refresh the access token; the rotated refresh token replaces the old one."""
    response = httpx.post(
        TOKEN,
        data={
            "grant_type": "refresh_token",
            "client_id": record["client_id"],
            "refresh_token": record["refresh_token"],
            "resource": RESOURCE,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        raise ValueError("siwc_refresh_failed: sign in again and re-import the credentials")
    tokens = response.json()
    tokens.setdefault("id_token", record.get("id_token"))
    tokens.setdefault("refresh_token", record["refresh_token"])
    tokens.setdefault("scope", " ".join(record["scopes"]))
    claims = {"email": record["email"], "iss": record["issuer"], "sub": record["subject"]}
    return _record(tokens, record["client_id"], claims, record["ext_agent_host_id"])


# Deployed host: one encrypted credential row in Postgres (key IFD_CREDENTIAL_KEY, a Fernet key).
CREDENTIAL_DDL = (
    "CREATE TABLE IF NOT EXISTS siwc_credentials (id TEXT PRIMARY KEY, ciphertext BYTEA NOT NULL, "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
)
CREDENTIAL_LOCK = 4343


def _fernet():
    from cryptography.fernet import Fernet

    key = setting("IFD_CREDENTIAL_KEY")
    if not key:
        raise ValueError("missing_configuration: IFD_CREDENTIAL_KEY (Fernet key) is not set")
    return Fernet(key.encode())


def _db_write(conn, record: dict) -> None:
    conn.execute(CREDENTIAL_DDL)
    conn.execute(
        "INSERT INTO siwc_credentials (id, ciphertext) VALUES ('default', %s) ON CONFLICT (id) "
        "DO UPDATE SET ciphertext = EXCLUDED.ciphertext, updated_at = now()",
        (_fernet().encrypt(json.dumps(record).encode()),),
    )


def _db_access_token(dsn: str) -> str:
    import psycopg

    with psycopg.connect(dsn, prepare_threshold=None) as conn:
        conn.execute(f"SELECT pg_advisory_xact_lock({CREDENTIAL_LOCK})")
        conn.execute(CREDENTIAL_DDL)
        row = conn.execute(
            "SELECT ciphertext FROM siwc_credentials WHERE id = 'default'"
        ).fetchone()
        if not row:
            raise ValueError("siwc_not_imported: run `ifd-credentials import --move` locally")
        record = json.loads(_fernet().decrypt(bytes(row[0])))
        if record["expires_at"] - time.time() > REFRESH_MARGIN:
            return record["access_token"]
        record = _refreshed(record)
        _db_write(conn, record)  # commits with the lock held
        return record["access_token"]


def login(port: int = 1455, timeout: float = 300) -> dict[str, Any]:
    """Open the browser for Sign in with ChatGPT and store plan-usage credentials."""
    existing = json.loads(CREDENTIALS.read_text()) if CREDENTIALS.exists() else {}
    client_id = existing.get("client_id")
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(64)
    redirect = f"http://127.0.0.1:{port}/auth/callback"
    result: dict[str, Any] = {}
    done = threading.Event()

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            url = urlparse(self.path)
            if url.path != "/auth/callback":
                self.send_response(404)
                self.end_headers()
                return
            result.update({k: v[0] for k, v in parse_qs(url.query).items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"Infinite Flight Dispatcher: sign-in received. You can close this tab."
            )
            done.set()

        def log_message(self, *args):  # keep codes and tokens out of logs
            pass

    server = HTTPServer(("127.0.0.1", port), Callback)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    params = {
        "client_id": client_id or "dynamic_agent_client",
        "ext_agent_host_id": host_id(),
        "response_type": "code",
        "redirect_uri": redirect,
        "scope": SCOPES,
        "resource": RESOURCE,
        "state": state,
        "nonce": nonce,
        "code_challenge_method": "S256",
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()),
    }
    if client_id:
        if existing.get("id_token"):
            params["id_token_hint"] = existing["id_token"]
    else:
        params["agent_name_hint"] = AGENT_NAME
    webbrowser.open(AUTHORIZE + "?" + urlencode(params))
    print("Opened the browser for Sign in with ChatGPT; waiting for the callback...")
    try:
        if not done.wait(timeout):
            raise ValueError("siwc_error: sign-in timed out")
    finally:
        server.shutdown()
    if result.get("state") != state:
        raise ValueError("siwc_error: state mismatch; sign-in rejected")
    if result.get("error"):
        raise ValueError(f"siwc_error: {result['error']} (plan usage not granted)")
    returned = result.get("client_id")
    if client_id and returned and returned != client_id:
        raise ValueError("siwc_error: callback client_id differs from the saved registration")
    client_id = client_id or returned
    if not client_id or client_id == "dynamic_agent_client":
        raise ValueError("siwc_error: registration incomplete (no issued client_id)")
    response = httpx.post(
        TOKEN,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": result["code"],
            "code_verifier": verifier,
            "redirect_uri": redirect,
            "resource": RESOURCE,
        },
        timeout=30,
    )
    if response.status_code >= 400:
        raise ValueError(f"siwc_error: token exchange failed ({response.status_code})")
    tokens = response.json()
    claims = _validate_id_token(tokens["id_token"], client_id, nonce)
    if existing.get("subject") and existing["subject"] != claims.get("sub"):
        raise ValueError("siwc_error: signed in as a different account than the saved one")
    if PLAN_SCOPE not in (tokens.get("scope") or "").split():
        raise ValueError("siwc_error: ChatGPT plan usage permission was not granted")
    record = _save(tokens, client_id, claims)
    return {"status": "signed_in", "email": record["email"], "scopes": record["scopes"]}


def access_token() -> str:
    """Current access token, refreshed (serialized across processes) near expiry."""
    dsn = setting("DATABASE_URL")
    if dsn:
        return _db_access_token(dsn)
    if not CREDENTIALS.exists():
        raise ValueError("siwc_not_signed_in: run `uv run ifd-login` first")
    CONFIG.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(CONFIG / "refresh.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = json.loads(CREDENTIALS.read_text())
        if record["expires_at"] - time.time() > REFRESH_MARGIN:
            return record["access_token"]
        record = _refreshed(record)
        _write_private(CREDENTIALS, json.dumps(record, indent=2))
        return record["access_token"]


def _with_missing_delta(event, streamed: set[str]):
    """Yield the event, preceded by one argument delta when the route sent none for the call."""
    if event.type == "response.function_call_arguments.delta":
        streamed.add(event.item_id)
    elif (
        event.type == "response.function_call_arguments.done"
        and event.item_id not in streamed
        and event.arguments
    ):
        yield ResponseFunctionCallArgumentsDeltaEvent.model_construct(
            type="response.function_call_arguments.delta",
            item_id=event.item_id,
            output_index=event.output_index,
            sequence_number=event.sequence_number,
            delta=event.arguments,
        )
    yield event


class _ArgumentsFromDone:
    """Response stream that keeps function-call arguments sent only on their `done` event.

    The ChatGPT-plan route can stream a function call with no argument deltas, only
    `response.function_call_arguments.done` (observed for every call in a multi-call
    response). langchain-openai builds arguments from deltas alone, so those calls reached
    the tools with empty arguments. Re-emitting the final arguments as one delta keeps them.
    """

    def __init__(self, stream):
        self._stream = stream

    def __enter__(self):
        self._stream.__enter__()
        return self

    def __exit__(self, *exc):
        return self._stream.__exit__(*exc)

    def __iter__(self):
        streamed: set[str] = set()
        for event in self._stream:
            yield from _with_missing_delta(event, streamed)

    async def __aenter__(self):
        await self._stream.__aenter__()
        return self

    async def __aexit__(self, *exc):
        return await self._stream.__aexit__(*exc)

    async def __aiter__(self):
        streamed: set[str] = set()
        async for event in self._stream:
            for item in _with_missing_delta(event, streamed):
                yield item


class ChatGPTPlanModel(ChatOpenAI):
    """ChatOpenAI shaped for the ChatGPT-plan Responses route (preview rules)."""

    @model_validator(mode="after")
    def _keep_arguments_sent_on_done(self):
        sync, aio = self.root_client, self.root_async_client
        if sync is not None:
            create = sync.responses.create
            sync.responses.create = lambda **kw: _ArgumentsFromDone(create(**kw))
        if aio is not None:
            acreate = aio.responses.create

            async def wrapped(**kw):
                return _ArgumentsFromDone(await acreate(**kw))

            aio.responses.create = wrapped
        return self

    def _get_request_payload(self, input_, *, stop=None, **kwargs) -> dict:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for key in UNSUPPORTED:
            payload.pop(key, None)
        payload["store"] = False
        payload["stream"] = True
        items = []
        for item in payload.get("input", []):
            if item.get("type") == "reasoning":
                continue  # not stored server-side with store=false; history is replayed
            if item.get("role") == "system":
                item = {**item, "role": "developer"}
            if item.get("type") in ("function_call", "message") and "id" in item:
                item = {k: v for k, v in item.items() if k != "id"}
            items.append(item)
        payload["input"] = items
        tools = payload.get("tools") or []
        functions = [t for t in tools if t.get("type") == "function"]
        if functions:
            others = [t for t in tools if t.get("type") != "function"]
            payload["tools"] = others + [
                {
                    "type": "namespace",
                    "name": "dispatcher",
                    "description": "Infinite Flight Dispatcher tools.",
                    "tools": functions,
                }
            ]
        return payload


def chatgpt_model(model: str = "gpt-6-luna", effort: str = "low") -> ChatGPTPlanModel:
    return ChatGPTPlanModel(
        model=model,
        api_key=access_token,
        base_url=RESOURCE,
        use_responses_api=True,
        streaming=True,
        reasoning={"effort": effort},
        max_retries=2,  # transient 5xx/429 (observed 503); model calls have no side effects
    )


def main() -> None:
    print(json.dumps(login(), indent=2))


def credentials_main() -> None:
    """`ifd-credentials import --move` | `ifd-credentials status` (needs DATABASE_URL and key)."""
    import argparse

    import psycopg

    parser = argparse.ArgumentParser(prog="ifd-credentials")
    parser.add_argument("command", choices=["import", "status"])
    parser.add_argument(
        "--move",
        action="store_true",
        help="required for import: the local tokens are removed after import, because the "
        "deployed host now owns refreshes (a rotated refresh token invalidates the other copy)",
    )
    args = parser.parse_args()
    dsn = setting("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is not set (run under `doppler run`)")
    if args.command == "status":
        with psycopg.connect(dsn, prepare_threshold=None) as conn:
            conn.execute(CREDENTIAL_DDL)
            row = conn.execute(
                "SELECT ciphertext, updated_at FROM siwc_credentials WHERE id = 'default'"
            ).fetchone()
        if not row:
            raise SystemExit("no credentials imported")
        record = json.loads(_fernet().decrypt(bytes(row[0])))
        minutes = int((record["expires_at"] - time.time()) / 60)
        print(
            json.dumps(
                {
                    "client_id_prefix": record["client_id"][:7],
                    "host_id_kind": record["ext_agent_host_id"].split(":")[1],
                    "plan_scope": PLAN_SCOPE in record["scopes"],
                    "access_token_minutes_left": minutes,
                    "updated_at": row[1].isoformat(),
                }
            )
        )
        return
    if not args.move:
        raise SystemExit("import needs --move (see --help); nothing changed")
    if not CREDENTIALS.exists():
        raise SystemExit("not signed in locally; run `uv run ifd-login` first")
    record = json.loads(CREDENTIALS.read_text())
    if PLAN_SCOPE not in record["scopes"]:
        raise SystemExit("local credentials lack ChatGPT plan usage permission")
    record["ext_agent_host_id"] = f"urn:uuid:{uuid.uuid4()}"  # the deployed host's own ID
    with psycopg.connect(dsn, prepare_threshold=None) as conn:
        conn.execute(f"SELECT pg_advisory_xact_lock({CREDENTIAL_LOCK})")
        _db_write(conn, record)
    local = {k: record[k] for k in ("email", "issuer", "subject", "client_id")}
    local["ext_agent_host_id"] = host_id()
    _write_private(CREDENTIALS.with_name("siwc-registration.json"), json.dumps(local, indent=2))
    CREDENTIALS.unlink()
    print("imported for the deployed host; local tokens removed (registration kept).")
    print("For local use again: `uv run ifd-login` (reuses the registered client).")
