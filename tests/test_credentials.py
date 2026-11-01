"""Deployed-host credential store. Tokens here are FAKE; refresh calls are MOCKED."""

import json
import os
import time

import pytest
from cryptography.fernet import Fernet

from ifdispatcher import siwc

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="needs TEST_DATABASE_URL (Postgres)"
)


def fake_record(expires_in: float, token: str = "fake-access-1") -> dict:
    return {
        "email": "user@example.com",
        "issuer": "https://auth.openai.com",
        "subject": "sub-1",
        "client_id": "oaiapp_test",
        "ext_agent_host_id": "urn:uuid:00000000-0000-4000-8000-000000000000",
        "id_token": None,
        "access_token": token,
        "refresh_token": "fake-refresh-1",
        "token_type": "Bearer",
        "expires_at": time.time() + expires_in,
        "scopes": ["chatgpt.tokens.use.direct", "offline_access"],
        "saved_at": "now",
    }


@pytest.fixture
def db(monkeypatch):
    import psycopg

    dsn = os.environ["TEST_DATABASE_URL"]
    monkeypatch.setenv("IFD_CREDENTIAL_KEY", Fernet.generate_key().decode())
    with psycopg.connect(dsn) as conn:
        conn.execute("DROP TABLE IF EXISTS siwc_credentials")
    return dsn


def stored(dsn):
    import psycopg

    with psycopg.connect(dsn) as conn:
        raw = conn.execute("SELECT ciphertext FROM siwc_credentials").fetchone()[0]
    return bytes(raw)


def test_fresh_token_is_served_and_encrypted_at_rest(db):
    import psycopg

    with psycopg.connect(db) as conn:
        siwc._db_write(conn, fake_record(3600))
    assert siwc._db_access_token(db) == "fake-access-1"
    assert b"fake-access-1" not in stored(db)  # ciphertext, not plaintext


def test_expired_token_refreshes_and_persists_rotation(db, monkeypatch):
    import psycopg

    with psycopg.connect(db) as conn:
        siwc._db_write(conn, fake_record(-10))

    def rotated(record):
        new = fake_record(3600, token="fake-access-2")
        new["refresh_token"] = "fake-refresh-2"
        return new

    monkeypatch.setattr(siwc, "_refreshed", rotated)
    assert siwc._db_access_token(db) == "fake-access-2"
    record = json.loads(siwc._fernet().decrypt(stored(db)))
    assert record["refresh_token"] == "fake-refresh-2"


def test_missing_import_is_explicit(db):
    with pytest.raises(ValueError, match="siwc_not_imported"):
        siwc._db_access_token(db)
