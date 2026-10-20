"""Float on Release: when a Manufacturing Item revision is released, re-point every
instance of its older revisions, in each immediate parent MBOM, to the released one.

    released item  ->  older revisions (same name & type, created earlier)
                   ->  instances whose *target* is an older revision (locate)
                   ->  parent of each instance (must be in an editable state)
                   ->  POST .../dsmfg:MfgItem/{parent}/dsmfg:MfgItemInstance/{inst}/replace
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from .settings import LOG_DIR, Settings, import_tdx

log = logging.getLogger("float_on_release")

ITEM_PATH = "/resources/v1/modeler/dsmfg/dsmfg:MfgItem/{}"
RUN_LOG = LOG_DIR / "runs.jsonl"
_DATE_FORMATS = ("%m/%d/%Y %I:%M:%S %p", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ")


class FloatError(RuntimeError):
    pass


def _parse_date(text: str | None) -> datetime | None:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime((text or "").strip(), fmt)
        except ValueError:
            continue
    return None


def _rev_key(rev: str) -> tuple:
    """A < B < ... < Z < AA; '01' < '02'; 'A.1' < 'A.2' < 'B.1'."""
    parts = []
    for p in (rev or "").split("."):
        parts.append((0, int(p), "") if p.isdigit() else (1, len(p), p))
    return tuple(parts)


def _is_older(other: dict, released: dict) -> bool:
    a, b = _parse_date(other.get("created")), _parse_date(released.get("created"))
    if a and b and a != b:
        return a < b
    return _rev_key(other.get("revision", "")) < _rev_key(released.get("revision", ""))


class FloatOnRelease:
    """Plans and applies the float for one released item. One run at a time."""

    _lock = asyncio.Lock()

    def __init__(self, settings: Settings):
        self.settings = settings
        build_client, creds, ServiceEntry, spec_path = import_tdx(settings)
        spec = json.loads(spec_path.read_text())
        entry = ServiceEntry(name="manufacturing", file="Manufacturing.json",
                             server_preference="APIGateway")
        self._client: httpx.AsyncClient = build_client(spec, entry, creds)
        # Float on Release works as Owner (VPLMProjectAdministrator) by default, whatever
        # SecurityContext the shared tdx-mcp-server .env uses for its own tools.
        if settings.security_context:
            self._client.headers["SecurityContext"] = settings.security_context
        self._username = (creds.username or "").lower()

    async def aclose(self) -> None:
        await self._client.aclose()

    # -- REST helpers ------------------------------------------------------------
    async def _call(self, method: str, path: str, **kw: Any) -> dict:
        r = await self._client.request(method, path, **kw)
        if r.status_code >= 400:
            raise FloatError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:400]}")
        return r.json() if r.content else {}

    async def get_item(self, item_id: str) -> dict:
        data = await self._call("GET", f"/dsmfg:MfgItem/{item_id}",
                                params={"$mask": "dsmfg:MfgItemMask.Details"})
        members = data.get("member") or []
        if not members:
            raise FloatError(f"Manufacturing Item {item_id} not found")
        return members[0]

    async def revisions_of(self, item: dict) -> list[dict]:
        data = await self._call("GET", "/dsmfg:MfgItem/search",
                                params={"$searchStr": item["name"], "$top": 1000})
        return [m for m in data.get("member", [])
                if m.get("name") == item["name"] and m.get("type") == item.get("type")]

    async def where_used(self, refs: list[dict]) -> list[dict]:
        """Instances whose target (child) is one of `refs`."""
        body = {"referencedObjects": [{
            "source": "$3DSpace", "type": r.get("type", ""), "identifier": r["id"],
            "relativePath": ITEM_PATH.format(r["id"])} for r in refs],
            "filterResults": "target"}
        data = await self._call("POST", "/dsmfg:MfgItemInstance/locate", json=body)
        out = []
        for m in data.get("member", []):
            for inst in (m.get("dsmfg:MfgItemInstance") or {}).get("member", []):
                out.append(inst)
        return out

    async def resolve(self, item: str) -> str:
        """A physical ID as-is, or a title/name -> its latest RELEASED revision (else latest)."""
        item = item.strip()
        if re.fullmatch(r"[0-9A-Fa-f]{32}", item):
            return item
        data = await self._call("GET", "/dsmfg:MfgItem/search",
                                params={"$searchStr": item, "$top": 100})
        hits = [m for m in data.get("member", [])
                if item.lower() in ((m.get("title") or "").lower(), (m.get("name") or "").lower())]
        released = [m for m in hits
                    if (m.get("state") or "").upper() == self.settings.released_state]
        pick = released or hits
        if not pick:
            raise FloatError(f"No Manufacturing Item titled or named '{item}'")
        pick.sort(key=lambda m: _parse_date(m.get("created")) or datetime.min, reverse=True)
        return pick[0]["id"]

    # -- planning ----------------------------------------------------------------
    async def plan(self, item_id: str) -> dict:
        released = await self.get_item(item_id)
        summary = {
            "item": {k: released.get(k) for k in ("id", "name", "title", "revision", "state", "type")},
            "changes": [], "skipped": [],
        }
        if (released.get("state") or "").upper() != self.settings.released_state:
            summary["result"] = f"not released (state {released.get('state')}); nothing to do"
            return summary

        family = await self.revisions_of(released)
        older = [r for r in family if r["id"] != released["id"] and _is_older(r, released)]
        summary["older_revisions"] = [{"id": r["id"], "revision": r.get("revision"),
                                       "state": r.get("state")} for r in older]
        if not older:
            summary["result"] = "no older revisions; nothing to float"
            return summary

        family_ids = {r["id"] for r in family}
        older_by_id = {r["id"]: r for r in older}
        instances = await self.where_used(older)
        parents: dict[str, dict] = {}
        for inst in instances:
            pid = (inst.get("parentObject") or {}).get("identifier")
            child_id = inst.get("reference") or (inst.get("referencedObject") or {}).get("identifier")
            if not pid or child_id not in older_by_id or pid in family_ids:
                continue
            if pid not in parents:
                parents[pid] = await self.get_item(pid)
            parent = parents[pid]
            row = {
                "parent_id": pid, "parent_title": parent.get("title"),
                "parent_name": parent.get("name"), "parent_revision": parent.get("revision"),
                "parent_state": parent.get("state"),
                "instance_id": inst["id"], "instance_name": inst.get("name"),
                "from_id": child_id, "from_revision": older_by_id[child_id].get("revision"),
                "to_id": released["id"], "to_revision": released.get("revision"),
                "source": (inst.get("referencedObject") or {}).get("source", "$3DSpace"),
                "type": released.get("type"),
            }
            reason = self._why_not_editable(parent)
            if reason:
                summary["skipped"].append({**row, "reason": reason})
            else:
                summary["changes"].append(row)
        summary["result"] = (f"{len(summary['changes'])} instance(s) to replace in "
                             f"{len({c['parent_id'] for c in summary['changes']})} parent(s); "
                             f"{len(summary['skipped'])} skipped")
        return summary

    def _why_not_editable(self, parent: dict) -> str:
        state = (parent.get("state") or "").upper()
        if state not in self.settings.editable_parent_states:
            return (f"parent is {state}; config.json editable_parent_states allows only "
                    f"{', '.join(self.settings.editable_parent_states)}")
        locked = (parent.get("reservedby") or "").lower()
        if locked and locked != self._username:
            return f"parent is reserved by {parent.get('reservedby')}"
        return ""

    # -- applying ----------------------------------------------------------------
    async def apply(self, plan: dict) -> dict:
        headers = {}
        if self.settings.change_action_id:
            ca = self.settings.change_action_id
            headers["DS-Change-Authoring-Context"] = json.dumps({
                "source": "$3DSpace", "type": "ChangeAction", "identifier": ca,
                "relativePath": f"/resources/v1/modeler/dslc/changeaction/{ca}"})
        for row in plan["changes"]:
            body = {"referencedObject": {
                "source": row["source"], "type": row["type"], "identifier": row["to_id"],
                "relativePath": ITEM_PATH.format(row["to_id"])}}
            try:
                await self._call(
                    "POST",
                    f"/dsmfg:MfgItem/{row['parent_id']}/dsmfg:MfgItemInstance/{row['instance_id']}/replace",
                    json=body, headers=headers)
                row["status"] = "replaced"
            except Exception as exc:  # keep going with the other parents
                row["status"] = "failed"
                row["error"] = str(exc)
        return plan

    async def run(self, item_id: str, dry_run: bool | None = None, trigger: str = "manual") -> dict:
        dry = self.settings.dry_run if dry_run is None else dry_run
        async with self._lock:
            plan = await self.plan(item_id)
            if plan["changes"]:
                if dry:
                    for row in plan["changes"]:
                        row["status"] = "dry-run (not changed)"
                else:
                    await self.apply(plan)
            plan.update(dry_run=dry, trigger=trigger,
                        at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            _append_run(plan)
            log.info("Float on Release %s rev %s: %s%s", plan["item"].get("title"),
                     plan["item"].get("revision"), plan.get("result"), " [DRY RUN]" if dry else "")
            return plan


def _append_run(plan: dict) -> None:
    with open(RUN_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(plan) + "\n")


def recent_runs(limit: int = 10) -> list[dict]:
    if not RUN_LOG.exists():
        return []
    lines = RUN_LOG.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(x) for x in reversed(lines) if x.strip()]
