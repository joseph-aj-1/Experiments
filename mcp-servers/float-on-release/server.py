"""Float on Release MCP server.

Tools:
  preview_float_on_release(item)  - what would change (never writes)
  float_on_release(item, apply)   - run it now for one item
  handle_eif_event(event_json)    - feed a captured EIF message through the same filter
  recent_float_runs(limit)        - the run log

Run:
  python server.py                 # stdio, for Claude Desktop (tools only)
  python server.py --http --watch  # long-running: tools over HTTP + the automatic agent
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastmcp import FastMCP

from float_on_release.core import FloatOnRelease, recent_runs
from float_on_release.settings import load_settings
from float_on_release.watcher import handle_message, watch

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

SETTINGS = load_settings()
_ENGINE: FloatOnRelease | None = None
_WATCH = False


def engine() -> FloatOnRelease:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = FloatOnRelease(SETTINGS)
    return _ENGINE


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(watch(SETTINGS, engine())) if _WATCH else None
    try:
        yield
    finally:
        if task:
            task.cancel()


mcp = FastMCP("Float on Release", lifespan=lifespan, instructions=(
    "Float on Release re-points Manufacturing Item instances in parent MBOMs from older "
    "revisions to the newly released revision. It runs automatically on EIF status-change "
    "events (to Released). Use preview first; only apply when the user asks."))


async def _resolve(item: str) -> str:
    return await engine().resolve(item)


@mcp.tool
async def preview_float_on_release(item: str) -> dict:
    """Show which parent MBOM instances would be re-pointed to this released item.
    `item` is a physical ID or a title such as 'AJ PP 301'. Never changes anything."""
    return await engine().run(await _resolve(item), dry_run=True, trigger="preview")


@mcp.tool
async def float_on_release(item: str, apply: bool = False) -> dict:
    """Float a released Manufacturing Item into its immediate parents' MBOMs.
    With apply=false (default) this is a dry run; apply=true performs the replaces
    (only in parents whose state is in config.json editable_parent_states; OBSOLETE is excluded by default)."""
    return await engine().run(await _resolve(item), dry_run=not apply, trigger="manual")


@mcp.tool
async def handle_eif_event(event_json: str) -> dict:
    """Process one EIF message (as saved by the EIF listener) exactly like the automatic
    agent would: it only acts on a Manufacturing Item status change to Released.
    Respects config.json dry_run."""
    return await handle_message(json.loads(event_json), engine(), SETTINGS, label="mcp")


@mcp.tool
def recent_float_runs(limit: int = 10) -> list[dict]:
    """The latest Float on Release runs (automatic and manual), newest first."""
    return recent_runs(limit)


@mcp.tool
def float_on_release_settings() -> dict:
    """Current agent settings (dry run, editable parent states, events folder)."""
    s = SETTINGS
    return {"dry_run": s.dry_run, "editable_parent_states": s.editable_parent_states,
            "released_state": s.released_state, "events_dir": str(s.events_dir),
            "status_event_types": s.status_event_types or "(auto-detect)",
            "change_action_id": s.change_action_id or None}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true", help="Serve over streamable-http")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--watch", action="store_true",
                        help="Also run the automatic agent (watch EIF events) inside this server")
    args = parser.parse_args()
    _WATCH = args.watch
    if args.http:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()
