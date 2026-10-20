"""Decides whether an EIF message is a Manufacturing Item "Status Change" to Released.

The EIF listener saves each message as {receivedAt, properties, body:{data:{...}}}.
A raw CloudEvent body ({data:{...}}) or just its `data` part is accepted as well.

The payload of the status-change event has not been captured yet, so matching is
deliberately two-step:
  1. cheap filter on the event itself: eventClass == Manufacturing Item and an
     eventType that looks like a state change (or is listed in
     config.json "status_event_types");
  2. the item's *current* state is read from 3DEXPERIENCE and must be RELEASED
     (done in core.plan). An event that names a different target state is
     dropped early.
"""
from __future__ import annotations

from dataclasses import dataclass

from .settings import Settings

# Event types that are certainly not a status change.
_NOT_STATUS = {"created", "modified", "deleted", "versioned", "revised", "attached", "detached"}
# Words that indicate a status/maturity change in an eventType or predicate.
_STATUS_WORDS = ("state", "status", "matur", "promot", "lifecycle", "transition", "release")
_STATE_NAMES = {"PRIVATE", "IN_WORK", "FROZEN", "RELEASED", "OBSOLETE"}


@dataclass
class Match:
    matched: bool
    reason: str
    item_id: str = ""
    event_type: str = ""


def _data(message: dict) -> dict:
    body = message.get("body", message)
    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return body["data"]
    return body if isinstance(body, dict) else {}


def _target_state(data: dict) -> str:
    """A state name mentioned in object.Value / object.newState / similar, if any."""
    obj = data.get("object")
    values = []
    if isinstance(obj, dict):
        values += [str(v) for v in obj.values() if isinstance(v, (str, int))]
    elif isinstance(obj, str):
        values.append(obj)
    for key in ("newState", "targetState", "state", "toState", "current"):
        if data.get(key):
            values.append(str(data[key]))
    for v in values:
        norm = v.strip().upper().replace(" ", "_")
        if norm in _STATE_NAMES:
            return norm
    return ""


def classify(message: dict, settings: Settings) -> Match:
    data = _data(message)
    event_class = data.get("eventClass", "")
    event_type = str(data.get("eventType") or message.get("body", {}).get("type") or "")
    subject = data.get("subject") or {}
    item_id = subject.get("identifier", "")

    if event_class != settings.event_class:
        return Match(False, f"eventClass '{event_class}' ignored", item_id, event_type)
    if not item_id:
        return Match(False, "no subject.identifier", item_id, event_type)

    et = event_type.lower()
    configured = {t.lower() for t in settings.status_event_types}
    predicate = str(data.get("predicate", "")).lower()
    if configured:
        is_status = et in configured
    else:
        is_status = et not in _NOT_STATUS and (
            any(w in et for w in _STATUS_WORDS) or any(w in predicate for w in _STATUS_WORDS))
    if not is_status:
        return Match(False, f"eventType '{event_type}' is not a status change", item_id, event_type)

    target = _target_state(data)
    if target and target != settings.released_state:
        return Match(False, f"status changed to {target}, not {settings.released_state}",
                     item_id, event_type)
    return Match(True, "status change; Released is confirmed against the item's live state",
                 item_id, event_type)
