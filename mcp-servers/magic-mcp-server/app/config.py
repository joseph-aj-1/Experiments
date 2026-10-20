"""Settings for the Catia Magic MCP server, loaded from .env."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    # Written by the Catia Magic plugin at startup: {"port": ..., "token": ...}
    token_file: Path = field(
        default_factory=lambda: Path(
            os.getenv("MAGIC_BRIDGE_TOKEN_FILE", str(Path.home() / ".magic-mcp" / "bridge.json"))
        ).expanduser()
    )
    # Optional override; normally the port comes from the token file.
    port_override: int | None = field(
        default_factory=lambda: int(os.getenv("MAGIC_BRIDGE_PORT")) if os.getenv("MAGIC_BRIDGE_PORT") else None
    )
    timeout_seconds: float = field(default_factory=lambda: float(os.getenv("MAGIC_TIMEOUT_SECONDS", "60")))
    # true -> only the read tools are registered
    read_only: bool = field(default_factory=lambda: _bool("MAGIC_READ_ONLY", "false"))
    # false -> delete_element is not registered even when edits are allowed
    allow_delete: bool = field(default_factory=lambda: _bool("MAGIC_ALLOW_DELETE", "true"))


SETTINGS = Settings()
