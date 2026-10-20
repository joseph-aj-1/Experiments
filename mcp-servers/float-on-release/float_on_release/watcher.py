"""Watches the EIF listener's events folder and runs Float on Release for every
Manufacturing Item status change to Released.

The EIF listener (eif-listener) already holds the durable subscription and writes
each message to events/*.json, so nothing else connects to the broker and no
event is missed while this agent is stopped: on restart it picks up the files
it has not processed yet.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from .core import FloatOnRelease
from .events import classify
from .settings import LOG_DIR, Settings

log = logging.getLogger("float_on_release.watcher")
STATE_FILE = LOG_DIR / "processed_events.json"
SEEN_LOG = LOG_DIR / "events_seen.log"


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=1))


def _note(line: str) -> None:
    with open(SEEN_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


async def handle_message(message: dict, engine: FloatOnRelease, settings: Settings,
                         label: str = "event") -> dict:
    m = classify(message, settings)
    _note(f"{label}\t{m.event_type}\t{m.item_id}\t{'MATCH' if m.matched else 'skip'}\t{m.reason}")
    if not m.matched:
        return {"matched": False, "reason": m.reason, "item_id": m.item_id, "event_type": m.event_type}
    result = await engine.run(m.item_id, trigger=f"eif:{label}")
    return {"matched": True, "event_type": m.event_type, "run": result}


async def watch(settings: Settings, engine: FloatOnRelease) -> None:
    folder: Path = settings.events_dir
    folder.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    if not state and not settings.process_existing_events:
        # First start: everything already in the folder is history, not a new release.
        state = {p.name: "existing" for p in folder.glob("*.json")}
        _save_state(state)
    log.info("Watching %s (dry_run=%s). %d earlier event file(s) ignored.",
             folder, settings.dry_run, len(state))

    while True:
        for path in sorted(folder.glob("*.json")):
            if path.name in state:
                continue
            try:
                message = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue  # still being written; retry on the next pass
            try:
                outcome = await handle_message(message, engine, settings, label=path.name)
                state[path.name] = "run" if outcome["matched"] else "skipped"
            except Exception as exc:
                log.exception("Float on Release failed for %s", path.name)
                _note(f"{path.name}\tERROR\t{exc}")
                state[path.name] = f"error: {exc}"[:300]
            _save_state(state)
        await asyncio.sleep(settings.poll_seconds)
