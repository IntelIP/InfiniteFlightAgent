"""Local settings from the environment, falling back to the Git-ignored project .env."""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def setting(name: str) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            key, _, raw = line.partition("=")
            if key.strip() == name and raw.strip():
                return raw.strip()
    return None


def data_dir() -> Path:
    return Path(setting("IFD_DATA_DIR") or Path(__file__).resolve().parents[2] / "data")


def export_tracing_settings() -> bool:
    """Copy LANGSMITH_* settings from .env into the process environment for LangChain tracing."""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip().startswith("LANGSMITH_") and value.strip():
                os.environ.setdefault(key.strip(), value.strip())
    return os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
