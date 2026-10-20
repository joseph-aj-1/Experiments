"""Float on Release settings (config.json) and access to the tdx-mcp-server auth code.

Float on Release does not keep its own credentials. It imports the 3DEXPERIENCE
client (3DPassport login, SecurityContext, APIKey, CSRF) from the existing
tdx-mcp-server project, which also loads that project's .env.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config.json"
LOG_DIR = ROOT / "logs"


@dataclass
class Settings:
    tdx_server_dir: Path
    events_dir: Path
    security_context: str = ""
    dry_run: bool = True
    released_state: str = "RELEASED"
    editable_parent_states: list[str] = field(
        default_factory=lambda: ["PRIVATE", "IN_WORK", "FROZEN", "RELEASED"])
    event_class: str = "Manufacturing Item"
    status_event_types: list[str] = field(default_factory=list)
    poll_seconds: float = 5
    process_existing_events: bool = False
    change_action_id: str = ""


def _resolve(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (ROOT / path).resolve()


def load_settings() -> Settings:
    raw = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    s = Settings(
        tdx_server_dir=_resolve(raw.get("tdx_server_dir", "../tdx-mcp-server")),
        events_dir=_resolve(raw.get("events_dir", "../eif-listener/events")),
        security_context=(raw.get("security_context") or "").strip(),
        dry_run=bool(raw.get("dry_run", True)),
        released_state=str(raw.get("released_state", "RELEASED")).upper(),
        editable_parent_states=[x.upper() for x in raw.get(
            "editable_parent_states", ["PRIVATE", "IN_WORK", "FROZEN", "RELEASED"])],
        event_class=raw.get("event_class", "Manufacturing Item"),
        status_event_types=list(raw.get("status_event_types", []) or []),
        poll_seconds=float(raw.get("poll_seconds", 5)),
        process_existing_events=bool(raw.get("process_existing_events", False)),
        change_action_id=raw.get("change_action_id", "") or "",
    )
    LOG_DIR.mkdir(exist_ok=True)
    return s


def import_tdx(settings: Settings):
    """Make tdx-mcp-server's `app` package importable and return what we need from it."""
    server_dir = settings.tdx_server_dir
    if not (server_dir / "app" / "client_factory.py").exists():
        raise RuntimeError(
            f"tdx-mcp-server not found at {server_dir}. Set 'tdx_server_dir' in config.json."
        )
    if str(server_dir) not in sys.path:
        sys.path.insert(0, str(server_dir))
    from app.client_factory import build_client  # type: ignore
    from app.config import CREDENTIALS, ServiceEntry  # type: ignore

    return build_client, CREDENTIALS, ServiceEntry, server_dir / "specs" / "Manufacturing.json"
