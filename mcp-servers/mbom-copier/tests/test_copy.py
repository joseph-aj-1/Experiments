"""Offline tests for mbom_copy.py with two in-memory dsmfg tenants.

    python tests/test_copy.py
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import itertools
import json
import re
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import mbom_copy  # noqa: E402

mbom_copy.RUNS = HERE / "runs"


class Tenant:
    """dsmfg item / instance / search endpoints, shaped like the APIGateway responses."""

    def __init__(self, tid: str, fail_writes_after: int | None = None):
        self.tid, self.fail_after = tid, fail_writes_after
        self.ids = (f"{tid[-4:]}{n:028X}" for n in itertools.count(1))
        self.seq = itertools.count(1)
        self.items: dict[str, dict] = {}
        self.inst: dict[str, list[dict]] = {}
        self.writes, self.calls = 0, []

    def add(self, title, typ="CreateAssembly", **extra):
        iid = next(self.ids)
        self.items[iid] = {"id": iid, "title": title, "type": typ, "name": f"{typ[:4].lower()}-{self.tid}-{next(self.seq):08d}",
                           "revision": "A", "state": "IN_WORK", "description": f"desc of {title}", **extra}
        self.inst[iid] = []
        return iid

    def link(self, parent, child, **attrs):
        typ = "ProcessInstanceContinuous" if self.items[child]["type"].startswith("ProcessContinuous") else "DELFmiFunctionIdentifiedInstance"
        i = {"id": next(self.ids), "name": f"{self.items[child]['title']}.{len(self.inst[parent]) + 1}", "type": typ,
             "referencedObject": {"identifier": child, "type": self.items[child]["type"]}, **attrs}
        self.inst[parent].append(i)
        return i["id"]

    def handler(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path.split("/api/dsmfg/v1", 1)[1]
        self.calls.append((req.method, path))
        if req.headers.get("SecurityContext") != "ctx::Role.Org.Space" and req.headers.get("SecurityContext") != "Role.Org.Space":
            pass
        body = json.loads(req.content) if req.content else None
        if req.method != "GET":
            self.writes += 1
            if self.fail_after is not None and self.writes > self.fail_after:
                return httpx.Response(503, text="Service unavailable")
        if req.method == "GET" and path == "/dsmfg:MfgItem/search":
            q = req.url.params.get("$searchStr", "").lower()
            return self.ok([i for i in self.items.values() if q in i["title"].lower() or q in i["name"].lower()])
        if req.method == "POST" and path == "/dsmfg:MfgItem":
            it = body["items"][0]
            iid = self.add(it["attributes"]["title"], it["type"])
            self.items[iid].update({k: v for k, v in it["attributes"].items() if k != "title"})
            return self.ok([self.items[iid]])
        m = re.fullmatch(r"/dsmfg:MfgItem/(\w+)/dsmfg:MfgItemInstance", path)
        if m:
            pid = m.group(1)
            if pid not in self.items:
                return httpx.Response(404, json={"message": "not found"})
            if req.method == "GET":
                return self.ok(self.inst[pid])
            out = []
            for spec in body["instances"]:
                cid = spec["referencedObject"]["identifier"]
                if cid not in self.items:
                    return httpx.Response(400, json={"message": f"reference {cid} not found"})
                q = (spec.get("attributes") or {}).get("quantity")
                if q is not None and set(q) != {"magnitude", "inputValue", "inputUnit"}:
                    return httpx.Response(400, json={"message": "Payload is not valid: quantity"})
                iid = self.link(pid, cid, **(spec.get("attributes") or {}))
                out.append({"id": iid})
            return self.ok(out)
        m = re.fullmatch(r"/dsmfg:MfgItem/(\w+)", path)
        if m and req.method == "GET":
            it = self.items.get(m.group(1))
            return self.ok([it]) if it else httpx.Response(404, json={"message": "Object not found"})
        return httpx.Response(404, json={"message": f"no route {req.method} {path}"})

    @staticmethod
    def ok(member):
        return httpx.Response(200, json={"totalItems": len(member), "member": member})

    def client(self):
        c = httpx.AsyncClient(base_url=f"https://{self.tid.lower()}-eu1-apigateway.test/api/dsmfg/v1",
                              transport=httpx.MockTransport(self.handler), headers={"SecurityContext": "ctx::Role.Org.Space"})
        c.tenant_id = self.tid
        return c

    def tree(self, iid, level=0):
        """[(level, title, type)] depth-first, for comparing structures across tenants."""
        out = [(level, self.items[iid]["title"], self.items[iid]["type"])]
        for i in self.inst[iid]:
            out += self.tree(i["referencedObject"]["identifier"], level + 1)
        return out


def make_source():
    s = Tenant("OI000629352")
    a = s.add("AJ MA 101", planningRequired="2", outsourced="1", **{"dsmfg:EnterpriseReference": {"partNumber": "PN-101"}})
    b = s.add("AJ MA 100")
    c = s.add("AJ PP 100", "Provide")
    d = s.add("AJ PP 200", "Provide")
    cpr = s.add("Glue", "ProcessContinuousProvide")
    s.link(a, b); s.link(a, c); s.link(a, b)               # B used twice under A
    s.link(a, cpr, quantity={"magnitude": "LENGTH", "unit": "METER", "value": 0.5}, isConstQty=False)   # read shape
    s.link(b, cpr)                                                                                   # no quantity set
    s.link(b, c); s.link(b, d)                             # C shared by A and B
    s.add("AJ MA 101 old")                                 # makes the title search non-unique
    return s, a


fails = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


def run(argv, src, tgt, stdin=""):
    out = io.StringIO()
    old_in = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            rc = asyncio.run(mbom_copy.main(argv, clients=(src.client(), tgt.client())))
    finally:
        sys.stdin = old_in
    return rc, out.getvalue()


def latest_run():
    return max(mbom_copy.RUNS.glob("*.json"), key=lambda p: p.stat().st_mtime)


def main():
    import shutil
    shutil.rmtree(mbom_copy.RUNS, ignore_errors=True)

    # 1) dry run
    src, a = make_source()
    tgt = Tenant("OI000999001")
    rc, out = run(["AJ MA 101"], src, tgt)
    check(rc == 0, "dry run exits 0")
    check(src.writes == 0 and tgt.writes == 0, "dry run writes nothing to either tenant")
    check("To create in OI000999001: 5 items, 7 instances" in out, "plan counts: 5 distinct items, 7 instances")
    check("(same item as above)" in out, "shared sub-assembly shown once, later marked as a repeat")
    check("Dry run: nothing was written" in out, "dry run says nothing was written")
    plan_file = latest_run()
    check(json.loads(plan_file.read_text())["status"] == "planned", "plan saved as a run record")

    # 2) ambiguous / missing root
    rc, out = run(["AJ MA"], src, tgt)
    check(rc == 2, "partial title with several matches is refused (asks for an ID)")
    rc, out = run(["Nope"], src, tgt)
    check(rc == 2, "unknown item is refused")

    # 3) execute without confirmation answer stops
    rc, out = run(["AJ MA 101", "--execute"], src, tgt, stdin="no\n")
    check(rc == 1 and tgt.writes == 0, "execute asks for confirmation; anything but 'yes' writes nothing")

    # 4) execute, with a failure part-way (target goes down after 4 writes), then resume
    tgt_f = Tenant("OI000999001", fail_writes_after=4)
    rc, out = run(["AJ MA 101", "--execute", "--yes"], src, tgt_f)
    rec_path = latest_run()
    rec = json.loads(rec_path.read_text())
    check(rc == 1 and rec["status"] == "incomplete" and "--resume" in out, "a failing target leaves an incomplete run and says how to resume")
    made_items = len(tgt_f.items)
    tgt_f.fail_after = None
    rc, out = run(["--resume", str(rec_path), "--execute", "--yes"], src, tgt_f)
    rec = json.loads(rec_path.read_text())
    check(rc == 0 and rec["status"] == "done", "resume finishes the copy (%s)" % rec["status"])
    root_t = rec["items"][a]["target_id"]
    check(len(tgt_f.items) == 5 and made_items <= 5, "no item created twice across the failed run and the resume (%d items)" % len(tgt_f.items))
    check([t[1:] for t in tgt_f.tree(root_t)] == [t[1:] for t in src.tree(a)], "target structure equals the source, BOM order included")
    check(src.writes == 0, "the source is never written to")
    check(rec["verification"]["problems"] == [] and rec["verification"]["parents_checked"] == 2, "read-back verification passes")
    ti = tgt_f.items[root_t]
    check(ti.get("planningRequired") == "Yes" and ti.get("outsourced") == "No" and ti.get("description") == "desc of AJ MA 101"
          and ti.get("dsmfg:EnterpriseReference") == {"partNumber": "PN-101"}, "description, planning required, outsourced, part number copied")
    glue_inst = [i for i in tgt_f.inst[root_t] if tgt_f.items[i["referencedObject"]["identifier"]]["title"] == "Glue"]
    check(glue_inst and glue_inst[0].get("quantity") == {"magnitude": "LENGTH", "inputValue": "0.5", "inputUnit": "METER"}
          and glue_inst[0].get("isConstQty") is False, "continuous quantity read as value/unit is created as inputValue/inputUnit")
    bt = rec["items"][[k for k, v in rec["tree"]["items"].items() if v["title"] == "AJ MA 100"][0]]["target_id"]
    g2 = [i for i in tgt_f.inst[bt] if tgt_f.items[i["referencedObject"]["identifier"]]["title"] == "Glue"]
    check(g2 and "quantity" not in g2[0], "continuous instance without a source quantity is created without one")

    # 5) run again on the finished target: nothing to create
    rc, out = run(["--resume", str(rec_path), "--execute", "--yes"], src, tgt_f)
    check(rc == 0 and "Nothing to create" in out and len(tgt_f.items) == 5, "re-running a finished copy creates nothing")

    # 6) reuse existing: the target already has AJ MA 100 (with its own BOM)
    tgt_r = Tenant("OI000999002")
    existing_b = tgt_r.add("AJ MA 100")
    rc, out = run(["AJ MA 101", "--execute", "--yes", "--reuse-existing"], src, tgt_r)
    rec = json.loads(latest_run().read_text())
    acts = {rec["tree"]["items"][k]["title"]: v["action"] for k, v in rec["items"].items()}
    check(acts == {"AJ MA 101": "create", "AJ MA 100": "reuse", "AJ PP 100": "create", "AJ PP 200": "inside", "Glue": "create"},
          "reuse: same-title item reused, items only used inside it are not copied (%s)" % acts)
    check(rc == 0 and tgt_r.inst[existing_b] == [], "reused item's own structure is left untouched")
    newroot = rec["items"][a]["target_id"]
    check(sum(1 for i in tgt_r.inst[newroot] if i["referencedObject"]["identifier"] == existing_b) == 2, "new parent instances the reused item twice")

    # 7) without --reuse-existing, an existing title is reported but a new item is created
    tgt_n = Tenant("OI000999003")
    tgt_n.add("AJ MA 100")
    rc, out = run(["AJ MA 101"], src, tgt_n)
    check("already exists in the target" in out and "5 items" in out, "existing titles are flagged in the dry run")

    # 8) title suffix + same tenant warning
    rc, out = run([a, "--title-suffix", " (copy)"], src, src)
    check("AJ MA 101 (copy)" in out and "same tenant" in out and src.writes == 0, "physical ID as root, suffix shown, same-tenant warning")

    print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
