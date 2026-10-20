"""HTTP client for the localhost bridge the Catia Magic plugin runs."""
from __future__ import annotations

import json
from typing import Any

import httpx
from fastmcp.exceptions import ToolError

from app.config import SETTINGS

NOT_RUNNING = (
    "Can't reach Catia Magic. Make sure Catia Magic Systems of Systems Architect is open "
    "and the 'Magic MCP Bridge' plugin is installed (see README)."
)


def _connection() -> tuple[str, str]:
    """Read port + token fresh on every call, so restarting Catia Magic just works."""
    try:
        info = json.loads(SETTINGS.token_file.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ToolError(NOT_RUNNING + f" (no bridge file at {SETTINGS.token_file})")
    except (OSError, ValueError) as e:
        raise ToolError(f"Could not read bridge file {SETTINGS.token_file}: {e}")
    port = SETTINGS.port_override or int(info["port"])
    return f"http://127.0.0.1:{port}", str(info["token"])


async def call(action: str, payload: dict[str, Any] | None = None) -> Any:
    """POST /api/<action> and return the 'result' field, or raise ToolError."""
    base, token = _connection()
    body = {k: v for k, v in (payload or {}).items() if v is not None}
    try:
        async with httpx.AsyncClient(timeout=SETTINGS.timeout_seconds) as client:
            r = await client.post(f"{base}/api/{action}", json=body, headers={"X-Bridge-Token": token})
    except httpx.ConnectError:
        raise ToolError(NOT_RUNNING)
    except httpx.TimeoutException:
        raise ToolError(
            f"Catia Magic did not answer within {SETTINGS.timeout_seconds:.0f}s "
            "(a modal dialog may be open, or the model is very large)."
        )
    try:
        data = r.json()
    except ValueError:
        raise ToolError(f"Bridge returned HTTP {r.status_code} with a non-JSON body")
    if not data.get("ok"):
        raise ToolError(data.get("error") or f"Bridge error (HTTP {r.status_code})")
    return data.get("result")
