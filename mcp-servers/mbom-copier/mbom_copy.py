"""Copy a Manufacturing Item structure (MBOM) from one 3DEXPERIENCE tenant to another.

    python mbom_copy.py "AJ MA 101"                    # dry run: read, check, print the plan
    python mbom_copy.py "AJ MA 101" --execute          # create it in the target
    python mbom_copy.py --resume runs/<file>.json --execute   # finish a run that stopped

The source and target connections come from source.env and target.env (same keys as
tdx-mcp-server's .env). Nothing is written to either tenant without --execute, and
nothing is ever written to the source.

What is copied: every distinct Manufacturing Item below the root (type, title,
description, part number, planning required, outsourced) and every instance, in BOM
order. Shared sub-assemblies are created once and instanced wherever they are used.
What is not copied: links to engineering (scope / implement), MEIs and sourcing,
configuration and effectivity, documents, change objects, revisions and states.

Order: items first, then each parent's instances. Every success is written to the
run record (runs/*.json) at once, so a run that stops can be resumed without
creating anything twice. The run ends by reading the target back and comparing it
with the source.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from dataclasses import fields
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent
RUNS = ROOT / "runs"
MFG = "/dsmfg:MfgItem"
REL = "/resources/v1/modeler/dsmfg/dsmfg:MfgItem/{}"
DETAILS = {"$mask": "dsmfg:MfgItemMask.Details"}
INST_DETAILS = {"$mask": "dsmfg:MfgItemInstanceMask.Details"}
MAX_DEPTH = 25
RETRY_DELAY = 2.0          # seconds; doubled/tripled on later attempts
CONTINUOUS_REFS = {"ProcessContinuousProvide", "ProcessContinuousCreateMaterial", "ContinuousByProduct"}
TYPE_LABELS = {"CreateAssembly": "Mfg Assembly", "Provide": "Provided Part", "CreateMaterial": "Mfg Material",
               "CreateKit": "Kit", "ProcessContinuousProvide": "Continuous Provided Material",
               "ProcessContinuousCreateMaterial": "Continuous Mfg Material"}

log = logging.getLogger("mbom_copy")


class CopyError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- connections
def load_profile(path: Path):
    """Credentials for one tenant from an env file, without touching os.environ."""
    sys.path.insert(0, str(ROOT))
    from app.config import Credentials  # type: ignore

    if not path.exists():
        raise CopyError(f"{path.name} not found. Copy {path.name}.example to {path.name} and fill it in.")
    env = {k: (v or "") for k, v in dotenv_values(path).items()}
    keymap = {"authorization": "Authorization", "security_context": "SecurityContext", "api_key": "APIKey",
              "base_url": "TDX_BASE_URL", "apigateway_url": "TDX_APIGATEWAY_URL",
              "server_preference": "TDX_SERVER_PREFERENCE", "username": "TDX_USERNAME", "password": "TDX_PASSWORD",
              "passport_url": "TDX_PASSPORT_URL", "tenant": "TDX_TENANT", "space_url": "TDX_SPACE_URL"}
    kw = {f: env.get(k, "") for f, k in keymap.items() if f in {x.name for x in fields(Credentials)}}
    kw["server_preference"] = kw.get("server_preference") or "APIGateway"
    kw["verify_ssl"] = env.get("TDX_VERIFY_SSL", "true").lower() != "false"
    kw["timeout_seconds"] = float(env.get("TDX_TIMEOUT_SECONDS") or 60)
    creds = Credentials(**kw)
    missing = [k for k, v in (("SecurityContext", creds.security_context), ("TDX_BASE_URL", creds.base_url)) if not v]
    if creds.server_preference == "APIGateway" and not creds.apigateway_url:
        missing.append("TDX_APIGATEWAY_URL")
    if missing:
        raise CopyError(f"{path.name}: set {', '.join(missing)}")
    return creds


DSMFG_SERVERS = [("3DSpace", "{3DSpace}/resources/v1/modeler/dsmfg"), ("APIGateway", "{APIGateway}/api/dsmfg/v1")]


def make_client(creds, servers=None, name: str = "dsmfg") -> httpx.AsyncClient:
    """Signed-in client for one web service; servers = [(variable, url template), ...]."""
    from app.client_factory import build_client, resolve_tenant  # type: ignore
    from app.config import ServiceEntry  # type: ignore

    spec = {"servers": [{"url": url, "variables": {var: {"default": f"https://my3DEXPERIENCE-{var}"}}}
                        for var, url in (servers or DSMFG_SERVERS)]}
    client = build_client(spec, ServiceEntry(name=name, file="", server_preference=creds.server_preference), creds)
    client.tenant_id = resolve_tenant(creds, str(client.base_url)) or "?"
    return client


class Api:
    """dsmfg calls for one tenant, with retries on throttling / gateway hiccups."""

    def __init__(self, client: httpx.AsyncClient, tenant: str, limit: int = 6):
        self.c, self.tenant, self.sem = client, tenant, asyncio.Semaphore(limit)

    async def call(self, method: str, path: str, **kw) -> dict:
        async with self.sem:
            for attempt in range(4):
                r = await self.c.request(method, path, **kw)
                if r.status_code in (429, 502, 503, 504) and attempt < 3:
                    await asyncio.sleep(RETRY_DELAY * (attempt + 1))
                    continue
                if r.status_code >= 400:
                    raise CopyError(f"{self.tenant}: {method} {path} -> HTTP {r.status_code}: {r.text[:400]}")
                data = r.json() if r.content else {}
                if isinstance(data, dict) and data.get("errorCode"):
                    raise CopyError(f"{self.tenant}: {method} {path} -> {data.get('message') or data.get('errorMessage')}"
                                    f" {data.get('errorDetails', '')}")
                return data
        raise CopyError(f"{self.tenant}: {method} {path} kept failing")

    @staticmethod
    def members(data: dict) -> list[dict]:
        d = data.get("result", data) if isinstance(data, dict) else {}
        return d.get("member", []) or []

    async def item(self, iid: str) -> dict | None:
        try:
            m = self.members(await self.call("GET", f"{MFG}/{iid}", params=DETAILS))
        except CopyError as e:
            if "HTTP 404" in str(e):
                return None
            raise
        return m[0] if m else None

    async def instances(self, iid: str, details: bool = True) -> list[dict]:
        return self.members(await self.call("GET", f"{MFG}/{iid}/dsmfg:MfgItemInstance", params=INST_DETAILS if details else None))

    async def search(self, text: str, top: int = 50) -> list[dict]:
        return self.members(await self.call("GET", f"{MFG}/search", params={"$searchStr": text, "$top": top}))


# --------------------------------------------------------------------------- source
def ref_id(inst: dict) -> str:
    return (inst.get("referencedObject") or {}).get("identifier") or inst.get("reference") or ""


async def resolve_root(src: Api, text: str) -> dict:
    text = text.strip()
    if re.fullmatch(r"[0-9A-Fa-f]{32}", text):
        it = await src.item(text.upper())
        if not it:
            raise CopyError(f"{src.tenant}: no Manufacturing Item with ID {text} (or not visible in your SecurityContext)")
        return it
    hits = await src.search(text, 50)
    exact = [h for h in hits if text in (h.get("title"), h.get("name"))]
    if len(exact) == 1:
        return await src.item(exact[0]["id"]) or exact[0]
    pool = exact or hits
    if not pool:
        raise CopyError(f"{src.tenant}: no Manufacturing Item matches '{text}' (new items take a minute to reach search)")
    lines = "\n".join(f"  {h.get('id')}  {h.get('title')}  ({h.get('name')}, rev {h.get('revision')}, {h.get('type')})" for h in pool[:20])
    raise CopyError(f"{src.tenant}: '{text}' matches {len(pool)} items; run again with one of these IDs:\n{lines}")


async def read_tree(src: Api, root: dict) -> dict:
    """{ root, items{id: item}, children{id: [ {inst, name, child, type, attrs} ]}, order[ids] }"""
    items, children = {root["id"]: root}, {}
    seen_item: dict[str, asyncio.Task] = {}

    async def visit(iid: str, path: tuple[str, ...]):
        if iid not in items:
            it = await src.item(iid)
            if not it:
                raise CopyError(f"{src.tenant}: child item {iid} could not be read (access?)")
            items[iid] = it
        if iid in children:
            return
        insts = await src.instances(iid)
        children[iid] = [{"inst": i.get("id"), "name": i.get("name") or i.get("title") or "", "child": ref_id(i),
                          "type": i.get("type") or "", "attrs": instance_attrs(i)} for i in insts]
        print(f"\r  read {len(items)} items…", end="", file=sys.stderr, flush=True)
        jobs = []
        for k in children[iid]:
            c = k["child"]
            if not c:
                raise CopyError(f"{src.tenant}: instance {k['inst']} under {items[iid].get('title')} has no reference")
            if c in path:
                raise CopyError(f"{src.tenant}: the structure has a cycle at {items[iid].get('title')} -> {c}")
            if len(path) >= MAX_DEPTH:
                raise CopyError(f"{src.tenant}: the structure is deeper than {MAX_DEPTH} levels")
            if c not in seen_item:
                seen_item[c] = asyncio.ensure_future(visit(c, path + (c,)))
            jobs.append(seen_item[c])
        await asyncio.gather(*jobs)

    await visit(root["id"], (root["id"],))
    print(file=sys.stderr)
    return finish_tree(root["id"], items, children, src.tenant)


def build_tree(root_id: str, items: dict, raw_children: dict, tenant: str = "source") -> dict:
    """Tree from data read elsewhere (the widget): items {id: item}, raw_children {id: [instance as read]}."""
    if root_id not in items:
        raise CopyError(f"{tenant}: the root item {root_id} is missing from the data")
    children = {pid: [{"inst": i.get("id"), "name": i.get("name") or i.get("title") or "", "child": ref_id(i),
                       "type": i.get("type") or "", "attrs": instance_attrs(i)} for i in insts]
                for pid, insts in raw_children.items()}
    return finish_tree(root_id, items, children, tenant)


def finish_tree(root_id: str, items: dict, children: dict, tenant: str) -> dict:
    """Check references, cycles and depth; add the depth-first order of distinct items."""
    order: list[str] = []          # distinct items, depth-first, first-seen

    def walk(i: str, path: tuple[str, ...]):
        order.append(i)
        if i not in children:
            raise CopyError(f"{tenant}: the instances of {items[i].get('title')} were not read")
        for k in children[i]:
            c = k["child"]
            if not c:
                raise CopyError(f"{tenant}: instance {k['inst']} under {items[i].get('title')} has no reference")
            if c not in items:
                raise CopyError(f"{tenant}: child item {c} under {items[i].get('title')} could not be read (access?)")
            if c in path:
                raise CopyError(f"{tenant}: the structure has a cycle at {items[i].get('title')} -> {items[c].get('title')}")
            if len(path) >= MAX_DEPTH:
                raise CopyError(f"{tenant}: the structure is deeper than {MAX_DEPTH} levels")
            if c not in order:
                walk(c, path + (c,))
    walk(root_id, (root_id,))
    return {"root": root_id, "items": {i: items[i] for i in order},
            "children": {i: children[i] for i in order}, "order": order}


def input_qty(q) -> dict | None:
    """{magnitude, unit, value} (as read) -> {magnitude, inputUnit, inputValue} (as created)."""
    if not isinstance(q, dict):
        return None
    val = q.get("inputValue", q.get("value"))
    unit = q.get("inputUnit", q.get("unit"))
    if val in (None, "") or not unit:
        return None
    return {"magnitude": q.get("magnitude", ""), "inputValue": str(val), "inputUnit": unit}


def instance_attrs(inst: dict) -> dict:
    """Instance attributes worth carrying over (quantity matters for continuous items)."""
    out = {}
    if inst.get("description"):
        out["description"] = inst["description"]
    # reads come back as {magnitude, unit, value}; creates take {magnitude, inputUnit, inputValue}
    q = input_qty(inst.get("quantity"))
    if q:
        out["quantity"] = q
    for k in ("contQuantity", "lossQuantity", "isConstQty", "useCase"):
        if inst.get(k) not in (None, ""):
            out[k] = inst[k]
    return out


CONTINUOUS_QTYS = ("refQuantity", "minLotQuantity", "incrementQuantity", "maxLotQuantity", "yieldQuantity")


def item_attrs(it: dict, title: str, magnitude: str = "") -> dict:
    a = {"title": title}
    if it.get("type") in CONTINUOUS_REFS:
        # continuous items must say what they are measured in (Length, Area, Mass, Volume)
        mag = it.get("magnitude") or magnitude
        if mag:
            a["magnitude"] = mag
        for k in CONTINUOUS_QTYS:
            q = input_qty(it.get(k))
            if q:
                a[k] = q
    if it.get("description"):
        a["description"] = it["description"]
    yes_no = {"2": "Yes", "1": "No", True: "Yes", False: "No", "Yes": "Yes", "No": "No"}
    for k in ("planningRequired", "outsourced"):
        if it.get(k) in yes_no:
            a[k] = yes_no[it[k]]
    pn = (it.get("dsmfg:EnterpriseReference") or {}).get("partNumber") or it.get("partNumber")
    if pn:
        a["dsmfg:EnterpriseReference"] = {"partNumber": pn}
    return a


# --------------------------------------------------------------------------- copier
def shown(path: Path) -> str:
    """Path as the user should type it (relative to the tool folder when possible)."""
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


class Copier:
    def __init__(self, source: str, tgt: Api, record: dict, record_path: Path, quiet: bool = False):
        self.source, self.tgt, self.rec, self.path, self.quiet = source, tgt, record, record_path, quiet
        self.assoc = None          # assoc.Associations, when associated objects are copied too

    def save(self):
        self.path.write_text(json.dumps(self.rec, indent=1))

    def say(self, msg: str):
        """Progress line: printed by the script, kept in the record for the widget."""
        self.rec.setdefault("events", []).append(msg)
        if not self.quiet:
            print(msg)

    def note(self, msg: str):
        self.rec["log"].append(f"{now()} {msg}")
        self.say(msg)
        self.save()

    @classmethod
    def new(cls, source: str, tgt: Api, tree: dict, reuse: bool, suffix: str, quiet: bool = False) -> "Copier":
        RUNS.mkdir(exist_ok=True)
        root = tree["items"][tree["root"]]
        safe = re.sub(r"[^A-Za-z0-9]+", "_", root.get("title") or root["id"])[:40]
        path = RUNS / f"{datetime.now():%Y%m%d-%H%M%S}_{safe}_{source}_to_{tgt.tenant}.json"
        rec = {"source": source, "target": tgt.tenant, "options": {"reuse_existing": reuse, "title_suffix": suffix},
               "started": now(), "status": "planned", "tree": tree,
               "items": {i: {"title": (tree["items"][i].get("title") or tree["items"][i].get("name") or "") + suffix}
                         for i in tree["order"]},
               "instances": {}, "log": []}
        return cls(source, tgt, rec, path, quiet)

    # ---------------------------------------------------------------- plan
    async def check_target(self):
        tree, opt = self.rec["tree"], self.rec["options"]

        async def one(iid: str):
            x, it = self.rec["items"][iid], tree["items"][iid]
            if x.get("created"):           # from an earlier run: still there?
                if await self.tgt.item(x["target_id"]):
                    return
                x.pop("created"); x.pop("target_id", None); x.pop("target_name", None)
                x["note"] = "created earlier but no longer in the target; will be created again"
            hits = [h for h in await self.tgt.search(x["title"]) if h.get("title") == x["title"] and h.get("type") == it.get("type")]
            x["matches"] = [{"id": h["id"], "name": h.get("name"), "revision": h.get("revision")} for h in hits]
            if opt["reuse_existing"] and len(hits) == 1:
                x.update(action="reuse", target_id=hits[0]["id"], target_name=hits[0].get("name"))
            else:
                x["action"] = "create"
                x.pop("target_id", None); x.pop("target_name", None); x.pop("note", None)
                if len(hits) > 1:
                    x["note"] = f"{len(hits)} items with this title already exist in the target" + \
                                ("; none reused (ambiguous)" if opt["reuse_existing"] else "")
                elif hits:
                    x["note"] = f"already exists in the target as {hits[0].get('name')} (use --reuse-existing to reuse it)"

        await asyncio.gather(*(one(i) for i in tree["order"]))
        # below a reused item nothing is copied: its structure already exists in the target
        reach: set[str] = set()

        def rec(i: str):
            if i in reach:
                return
            reach.add(i)
            if self.rec["items"][i]["action"] != "reuse":
                for k in tree["children"].get(i, []):
                    rec(k["child"])
        rec(tree["root"])
        for i in tree["order"]:
            x = self.rec["items"][i]
            if i not in reach and not x.get("created"):
                x["action"] = "inside"
        for pid, kids in tree["children"].items():
            parent = self.rec["items"][pid]
            for k in kids:
                r = self.rec["instances"].setdefault(k["inst"], {"parent": pid, "child": k["child"]})
                r["skip"] = parent["action"] != "create" and not r.get("target_id")
        if self.assoc:
            await self.assoc.plan()
        self.rec["checked"] = now()
        self.save()

    def warnings(self) -> list[str]:
        tree, w = self.rec["tree"], []
        for pid, kids in tree["children"].items():
            if self.rec["items"][pid]["action"] != "create":
                continue
            for k in kids:
                ct = tree["items"][k["child"]].get("type")
                if ct in CONTINUOUS_REFS and "quantity" not in k["attrs"]:
                    w.append(f"{tree['items'][pid].get('title')} -> {k['name'] or tree['items'][k['child']].get('title')}: "
                             "continuous instance with no quantity set in the source; the target will use its default")
        for i in tree["order"]:
            if (self.rec["items"][i]["action"] == "create" and tree["items"][i].get("type") in CONTINUOUS_REFS
                    and not self.magnitude_of(i)):
                w.append(f"{tree['items'][i].get('title')}: continuous item with no magnitude in the source; "
                         "the target will refuse to create it")
        if self.source == self.rec["target"]:
            w.append("source and target are the same tenant" + ("" if self.rec["options"]["title_suffix"] else
                     " and there is no --title-suffix: the copies will have the same titles as the originals"))
        if self.assoc:
            w += self.assoc.warnings()
        return w

    def counts(self) -> dict:
        c = {"create": 0, "created": 0, "reuse": 0, "inside": 0, "inst_create": 0, "inst_created": 0, "failed": 0}
        for x in self.rec["items"].values():
            if x["action"] == "create":
                c["created" if x.get("created") else "create"] += 1
            else:
                c[x["action"]] += 1
            c["failed"] += bool(x.get("error"))
        for r in self.rec["instances"].values():
            if not r.get("skip"):
                c["inst_created" if r.get("target_id") else "inst_create"] += 1
                c["failed"] += bool(r.get("error"))
        if self.assoc:
            a = self.assoc.counts()
            c["assoc"] = a
            c["assoc_todo"] = sum(a[k]["pending"] + a[k]["error"] for k in ("specs", "plants", "meis", "changeActions"))
            c["failed"] += self.assoc.failed()
        return c

    def plan_rows(self) -> list[dict]:
        """The plan as rows (tree order, shared items repeated once as 'repeat') for a UI."""
        tree, items, rows, printed = self.rec["tree"], self.rec["items"], [], set()

        def row(iid: str, level: int, inst: dict | None):
            it, x = tree["items"][iid], items[iid]
            r = {"level": level, "id": iid, "title": it.get("title") or "", "name": it.get("name") or "",
                 "type": it.get("type") or "", "type_label": TYPE_LABELS.get(it.get("type"), it.get("type") or ""),
                 "revision": it.get("revision") or "", "instance": (inst or {}).get("name", ""),
                 "action": "done" if x.get("created") else x["action"], "target_title": x.get("title"),
                 "target_name": x.get("target_name") or "", "target_id": x.get("target_id") or "",
                 "note": x.get("note") or "", "error": x.get("error") or "", "repeat": iid in printed}
            if self.assoc and iid not in printed:
                r["assoc"] = self.assoc.badges(iid)
            if inst:
                ir = self.rec["instances"].get(inst["inst"], {})
                r["quantity"] = (inst["attrs"].get("quantity") or {})
                r["instance_status"] = "skip" if ir.get("skip") else "done" if ir.get("target_id") else \
                    "error" if ir.get("error") else "pending"
                r["instance_error"] = ir.get("error") or ""
            rows.append(r)
            if r["repeat"]:
                return
            printed.add(iid)
            for k in tree["children"].get(iid, []):
                row(k["child"], level + 1, k)
        row(tree["root"], 0, None)
        return rows

    def print_plan(self):
        tree, items = self.rec["tree"], self.rec["items"]
        label = {"create": "CREATE", "reuse": "REUSE ", "inside": "  —   "}
        print(f"\nPlan: {self.source}  ->  {self.tgt.tenant}\n")
        print(f"{'Action':8} {'Structure':60} {'Type':22} {'Source name':28} Target")
        printed: set[str] = set()

        def row(iid: str, level: int, inst_name: str):
            it, x = tree["items"][iid], items[iid]
            act = "DONE  " if x.get("created") else label[x["action"]]
            again = iid in printed
            name = ("    " * level) + ("└ " if level else "") + (it.get("title") or "") + (f"  [{inst_name}]" if inst_name else "")
            tgt = x.get("target_name") or (x["title"] if x["action"] == "create" and x["title"] != it.get("title") else "")
            print(f"{act:8} {name[:60]:60} {TYPE_LABELS.get(it.get('type'), it.get('type') or '')[:22]:22} "
                  f"{(it.get('name') or '')[:28]:28} {tgt}{'  (same item as above)' if again else ''}")
            if x.get("note") and not again:
                print(f"{'':8} {'    ' * level}  ! {x['note']}")
            if again:
                return
            printed.add(iid)
            for k in tree["children"].get(iid, []):
                row(k["child"], level + 1, k["name"])
        row(tree["root"], 0, "")
        c = self.counts()
        print(f"\nTo create in {self.tgt.tenant}: {c['create']} items, {c['inst_create']} instances"
              + (f"  (already done by an earlier run: {c['created']} items, {c['inst_created']} instances)" if c["created"] or c["inst_created"] else "")
              + (f"\nReused from the target: {c['reuse']} items" if c["reuse"] else "")
              + (f"; {c['inside']} more sit inside them and are not copied" if c["inside"] else ""))
        for w in self.warnings():
            print(f"WARNING: {w}")

    def magnitude_of(self, iid: str) -> str:
        """The item's own magnitude, else the magnitude of a quantity on an instance of it."""
        tree = self.rec["tree"]
        if tree["items"][iid].get("magnitude"):
            return tree["items"][iid]["magnitude"]
        for kids in tree["children"].values():
            for k in kids:
                if k["child"] == iid and (k["attrs"].get("quantity") or {}).get("magnitude"):
                    return k["attrs"]["quantity"]["magnitude"]
        return ""

    # ---------------------------------------------------------------- execute
    async def create_items(self):
        tree = self.rec["tree"]
        todo = [i for i in tree["order"] if self.rec["items"][i]["action"] == "create" and not self.rec["items"][i].get("created")]

        async def one(iid: str):
            x, it = self.rec["items"][iid], tree["items"][iid]
            try:
                d = await self.tgt.call("POST", MFG, json={"items": [{"type": it["type"], "attributes": item_attrs(it, x["title"], self.magnitude_of(iid))}]})
                m = Api.members(d)[0]
                x.update(target_id=m["id"], target_name=m.get("name"), created=now())
                x.pop("error", None)
                self.say(f"  created {x['title']} -> {m.get('name')}")
            except Exception as e:
                x["error"] = str(e)
                self.say(f"  FAILED  {x['title']}: {e}")
            self.save()
        await asyncio.gather(*(one(i) for i in todo))

    async def create_instances(self):
        tree = self.rec["tree"]
        parents = [i for i in tree["order"] if self.rec["items"][i]["action"] == "create" and tree["children"].get(i)]

        async def under(pid: str):
            p = self.rec["items"][pid]
            n = 0
            for k in tree["children"][pid]:         # one at a time: keeps the source BOM order
                r = self.rec["instances"][k["inst"]]
                if r.get("skip") or r.get("target_id"):
                    continue
                c = self.rec["items"][k["child"]]
                if not p.get("target_id") or not c.get("target_id"):
                    r["error"] = "parent or child item was not created"
                    continue
                body = {"referencedObject": {"identifier": c["target_id"], "relativePath": REL.format(c["target_id"]),
                                             "type": tree["items"][k["child"]].get("type")}}
                if k["attrs"]:
                    body["attributes"] = k["attrs"]
                try:
                    d = await self.tgt.call("POST", f"{MFG}/{p['target_id']}/dsmfg:MfgItemInstance", json={"instances": [body]})
                    r.update(target_id=Api.members(d)[0]["id"], created=now())
                    r.pop("error", None)
                    n += 1
                except Exception as e:
                    r["error"] = str(e)
                    self.say(f"  FAILED  {p['title']} -> {c['title']}: {e}")
                self.save()
            if n:
                self.say(f"  {n} instance(s) under {p['title']}")
        await asyncio.gather(*(under(i) for i in parents))

    async def verify(self) -> list[str]:
        tree, items, problems = self.rec["tree"], self.rec["items"], []

        async def one(pid: str):
            want: dict[str, int] = {}
            for k in tree["children"][pid]:
                tid = items[k["child"]].get("target_id")
                want[tid] = want.get(tid, 0) + 1
            live = await self.tgt.instances(items[pid]["target_id"], details=False)
            got: dict[str, int] = {}
            for i in live:
                got[ref_id(i)] = got.get(ref_id(i), 0) + 1
            for cid in set(want) | set(got):
                if want.get(cid, 0) != got.get(cid, 0):
                    who = next((items[s]["title"] for s in items if items[s].get("target_id") == cid), cid)
                    problems.append(f"{items[pid]['title']}: {got.get(cid, 0)} x {who} in the target, expected {want.get(cid, 0)}")

        parents = [i for i in tree["order"] if items[i]["action"] == "create" and items[i].get("target_id") and tree["children"].get(i)]
        await asyncio.gather(*(one(i) for i in parents))
        self.rec["verification"] = {"at": now(), "parents_checked": len(parents), "problems": problems}
        self.save()
        return problems

    async def execute(self) -> bool:
        self.rec["status"] = "running"
        self.note(f"copy started: {self.source} -> {self.tgt.tenant}")
        await self.create_items()
        await self.create_instances()
        if self.assoc:
            await self.assoc.execute()
        c = self.counts()
        problems = await self.verify()
        if self.assoc:
            problems += await self.assoc.verify()
        root = self.rec["items"][self.rec["tree"]["root"]]
        if c["failed"]:
            self.rec["status"] = "incomplete"
            self.note(f"{c['failed']} step(s) failed. Fix the cause, then: python mbom_copy.py --resume {shown(self.path)} --execute")
            return False
        if problems:
            self.rec["status"] = "copied with differences"
            for p in problems:
                self.note(f"DIFFERENCE: {p}")
            return False
        self.rec["status"] = "done"
        self.rec["finished"] = now()
        self.note(f"done: {root['title']} is {root.get('target_name') or root.get('target_id')} in {self.tgt.tenant}; "
                  f"the target structure matches the source ({self.rec['verification']['parents_checked']} parents checked)")
        return True


# --------------------------------------------------------------------------- main
async def main(argv: list[str] | None = None, clients=None) -> int:
    ap = argparse.ArgumentParser(description="Copy an MBOM between 3DEXPERIENCE tenants (dry run unless --execute).")
    ap.add_argument("root", nargs="?", help="source Manufacturing Item: physical ID, exact title or name")
    ap.add_argument("--execute", action="store_true", help="create the copy (default: dry run, nothing is written)")
    ap.add_argument("--resume", help="run record (runs/*.json) of a copy to finish")
    ap.add_argument("--reuse-existing", action="store_true",
                    help="use a target item with the same title and type instead of creating one (its structure is not touched)")
    ap.add_argument("--title-suffix", default="", help="added to every created title, e.g. ' (copy)'")
    ap.add_argument("--source", default=str(ROOT / "source.env"), help="source connection (default source.env)")
    ap.add_argument("--target", default=str(ROOT / "target.env"), help="target connection (default target.env)")
    ap.add_argument("--yes", action="store_true", help="don't ask for confirmation before writing")
    a = ap.parse_args(argv)
    if not a.root and not a.resume:
        ap.error("give the source item, or --resume <run record>")

    side = f"source ({Path(a.source).name})"
    try:
        if clients:
            sc, tc = clients
        else:
            sc, tc = make_client(load_profile(Path(a.source))), make_client(load_profile(Path(a.target)))
        src, tgt = Api(sc, sc.tenant_id), Api(tc, tc.tenant_id)
        if a.resume:
            path = Path(a.resume).resolve()
            rec = json.loads(path.read_text())
            if (rec["source"], rec["target"]) != (src.tenant, tgt.tenant):
                raise CopyError(f"that run copies {rec['source']} -> {rec['target']}, but the env files point at "
                                f"{src.tenant} -> {tgt.tenant}")
            cp = Copier(src.tenant, tgt, rec, path)
            cp.rec["log"].append(f"{now()} resumed")
        else:
            print(f"Reading '{a.root}' from {src.tenant}…")
            root = await resolve_root(src, a.root)
            tree = await read_tree(src, root)
            cp = Copier.new(src.tenant, tgt, tree, a.reuse_existing, a.title_suffix)
        side = f"target ({Path(a.target).name})"
        print(f"Checking {tgt.tenant}…")
        await cp.check_target()
        cp.print_plan()
        c = cp.counts()
        print(f"\nRun record: {cp.path}")
        if not a.execute:
            print("Dry run: nothing was written. Add --execute to create the copy" +
                  (f" (or --resume {shown(cp.path)} --execute to create exactly this plan)." if c["create"] or c["inst_create"] else "."))
            return 0
        if not c["create"] and not c["inst_create"]:
            print("Nothing to create.")
            ok = not await cp.verify()
            return 0 if ok else 1
        if not a.yes:
            ans = input(f"\nCreate {c['create']} items and {c['inst_create']} instances in {tgt.tenant}? Type yes: ")
            if ans.strip().lower() != "yes":
                print("Stopped; nothing was written.")
                return 1
        return 0 if await cp.execute() else 1
    except CopyError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    except httpx.HTTPError as e:
        print(f"ERROR: could not reach the {side} tenant: {type(e).__name__}: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        if type(e).__name__ != "PassportLoginError":
            raise
        print(f"ERROR signing in to the {side} tenant: {e}\n"
              f"Check TDX_USERNAME, TDX_PASSWORD, APIKey and SecurityContext in that file. Trace: auth_debug.log", file=sys.stderr)
        return 2
    finally:
        if not clients:
            for c_ in ("sc", "tc"):
                cl = locals().get(c_)
                if cl is not None:
                    await cl.aclose()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(asyncio.run(main()))
