"""Associated objects (specifications, plants, MEIs, change actions) through the real service
against an in-memory target with every web service involved.

    python tests/test_assoc.py
"""
from __future__ import annotations

import base64
import json
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import assoc as ax  # noqa: E402
import mbom_copy  # noqa: E402
import mbom_service as svc  # noqa: E402
from mock_target import FullTenant  # noqa: E402
from test_copy import make_source, check, fails  # noqa: E402

mbom_copy.RETRY_DELAY = 0.01
TMP = Path(tempfile.mkdtemp())
mbom_copy.RUNS = TMP / "runs"
svc.TARGET_ENV = TMP / "target.env"
svc.CONFIG = TMP / "service.json"

PDF = b"%PDF-1.4 spec 00753-2350 " + bytes(range(256)) * 40
XLSX = b"PK\x03\x04 tolerances " + bytes(range(200))


def source_payload(src, root):
    items, children, todo = {}, {}, [root]
    while todo:
        i = todo.pop()
        if i in items:
            continue
        items[i] = src.items[i]
        children[i] = src.inst[i]
        todo += [x["referencedObject"]["identifier"] for x in src.inst[i]]
    return {"source_tenant": src.tid, "root": root, "items": items, "children": children}


def main() -> int:
    src, a = make_source()
    by = {v["title"]: k for k, v in src.items.items()}
    b, c, d, glue = by["AJ MA 100"], by["AJ PP 100"], by["AJ PP 200"], by["Glue"]

    tgt = FullTenant("R1132100000770")
    pune = tgt.add_plant("Pune")
    tgt.add_plant("Houston")
    existing_mei = tgt.add_mei("TI-555", "Texas Instruments")

    # plant lookup and change-action writes wait for Arun's specs; the test plugs in a lookup
    ax.PLANT_API["confirmed"] = True

    async def find_plant(self, name):
        return [p for p in tgt.plants.values() if p["name"].lower() == name.lower()]
    ax.Associations.find_plant = find_plant

    # what the widget sends: the structure + the associations it read from the source
    assoc = {
        "options": {"specs": True, "plants": True, "meis": True, "changeActions": True},
        "items": {
            a: {"specs": ["DOC1"], "plants": [{"id": "SRCPUNE", "name": "Pune", "makeOrBuy": "Make"}],
                "changeActions": [{"id": "CA1", "impact": "PROPOSED"}]},
            b: {"specs": ["DOC1", "DOC2"], "plants": [{"id": "SRCPUNE", "name": "Pune", "makeOrBuy": "Make"},
                                                     {"id": "SRCMUM", "name": "Mumbai", "makeOrBuy": "Buy"}],
                "changeActions": [{"id": "CA1", "impact": "REALIZED"}]},
            c: {"meis": [{"mei": "MEI1", "qualification": {"preferred": "TRUE", "approved": "Yes", "comments": "first source"}},
                         {"mei": "MEI2", "qualification": {"preferred": "FALSE", "approved": "Yes"}}],
                "plants": [{"id": "SRCHOU", "name": "Houston", "makeOrBuy": "Buy"}]},
        },
        "meis": {"MEI1": {"id": "MEI1", "title": "AJ MEI PP 100", "mpn": "AJ MEI PP 100", "manufacturer": "Hi-Tech Supplier",
                          "partSource": "catalog"},
                 "MEI2": {"id": "MEI2", "mpn": "TI-555", "manufacturer": "Texas Instruments"}},
        "docs": {"DOC1": {"id": "DOC1", "name": "DOC-0000001", "title": "00753-2350", "revision": "0", "description": "drawing",
                          "files": [{"id": "F1", "name": "00753-2350.pdf", "size": len(PDF)}]},
                 "DOC2": {"id": "DOC2", "name": "DOC-0000003", "title": "Tolerances", "files": [{"id": "F2", "name": "Tolerances.xlsx", "size": len(XLSX)}]}},
        "changeActions": {"CA1": {"id": "CA1", "name": "CA-00000012", "title": "Introduce AJ MA 101", "description": "new line",
                                  "severity": "Medium", "state": "In Work"}},
    }

    cfg = svc.load_config()
    engine = svc.Engine(target_factory=tgt.client, space_url=tgt.space, fcs_client=tgt.fcs_client())
    httpd = svc.serve(engine, port=0, cfg=cfg)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def call(method, path, body=None):
        req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-MBC-Token", cfg["token"])
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    def wait(run):
        for _ in range(600):
            _, v = call("GET", f"/runs/{run}")
            if v["status"] != "running":
                return v
            time.sleep(0.05)
        return v

    # ---------------------------------------------------------------- plan
    code, v = call("POST", "/plan", {**source_payload(src, a), "assoc": assoc})
    check(code == 200 and tgt.writes == 0, "plan with associations writes nothing (%s)" % (v.get("error") if code != 200 else "ok"))
    run = v["run"]
    ac = v["counts"]["assoc"]
    check(ac["specs"]["pending"] == 3 and ac["new"]["docs"] == 2, "specs: 3 links, 2 new documents")
    check(ac["plants"]["pending"] == 3 and ac["plants"]["skip"] == 1, "plants: Pune x2 + Houston linked, Mumbai skipped (%s)" % ac["plants"])
    check(ac["meis"]["pending"] == 2 and ac["new"]["meis"] == 1, "MEIs: one new, one reused from the target")
    check(any("Mumbai" in w for w in v["warnings"]), "missing plant named in the warnings")
    check(any("Change Action API spec" in w for w in v["warnings"]), "change actions flagged as waiting for the spec")
    rows = {r["title"]: r for r in v["rows"] if not r["repeat"]}
    ba = {x["kind"]: x for x in rows["AJ PP 100"]["assoc"] if x["kind"] == "meis" and "TI-555" in x["label"]}
    check(ba and ba["meis"]["action"] == "reuse", "row badge: TI-555 MEI reused")
    mum = [x for x in rows["AJ MA 100"]["assoc"] if x["kind"] == "plants" and "Mumbai" in x["label"]]
    check(mum and mum[0]["action"] == "missing" and mum[0]["status"] == "skip", "row badge: Mumbai missing, skipped")
    check(sorted(f["file"] for f in v["files_needed"]) == ["F1", "F2"], "service asks for the two spec files")

    # ---------------------------------------------------------------- files
    code, e = call("POST", f"/execute", {"run": run})
    v = wait(run)
    check(v["status"] == "failed" and "not received" in (v.get("error") or ""), "copy refuses to start without the spec files")
    check(len(tgt.items) == 0, "...and created nothing")
    code, e = call("POST", f"/runs/{run}/files", {"file": "NOPE", "data": ""})
    check(code == 400, "unknown file refused")
    code, r = call("POST", f"/runs/{run}/files", {"file": "F1", "data": base64.b64encode(PDF).decode()})
    check(code == 200 and r["bytes"] == len(PDF) and [f["file"] for f in r["files_needed"]] == ["F2"], "file upload stored, one left")
    call("POST", f"/runs/{run}/files", {"file": "F2", "data": base64.b64encode(XLSX).decode()})

    # ---------------------------------------------------------------- execute with Sourcing down
    tgt.fail_service = "qual"
    call("POST", "/execute", {"run": run})
    v = wait(run)
    check(v["status"] == "incomplete" and v["counts"]["assoc"]["meis"]["error"] == 2, "qualification failures leave the run incomplete (%s)" % v["status"])
    check(len(tgt.docs) == 2 and sum(len(x) for x in tgt.resp.values()) == 3, "documents and plant links done meanwhile")
    tgt.fail_service = None
    call("POST", "/execute", {"run": run})
    v = wait(run)
    check(v["status"] == "done", "retry finishes (%s %s)" % (v["status"], v.get("verification")))

    # ---------------------------------------------------------------- what the target holds
    t = {it["title"]: k for k, it in tgt.items.items()}
    ta, tb, tc = t["AJ MA 101"], t["AJ MA 100"], t["AJ PP 100"]
    docs = {d_["title"]: d_ for d_ in tgt.docs.values()}
    check(len(tgt.docs) == 2 and docs["00753-2350"]["parents"] == {ta, tb} and docs["Tolerances"]["parents"] == {tb},
          "each document created once and attached to every copied item that had it")
    check(docs["00753-2350"]["files"][0]["bytes"] == PDF and docs["00753-2350"]["files"][0]["name"] == "00753-2350.pdf"
          and docs["Tolerances"]["files"][0]["bytes"] == XLSX, "file contents arrive intact")
    check(docs["00753-2350"]["description"] == "drawing", "document description copied")
    plants = {(k, l["organizationRef"]["identifier"], l.get("makeOrBuy")) for k, ls in tgt.resp.items() for l in ls}
    hou = [p for p in tgt.plants.values() if p["name"] == "Houston"][0]["id"]
    check(plants == {(ta, pune, "Make"), (tb, pune, "Make"), (tc, hou, "Buy")}, "plant links with Make/Buy, Mumbai left out")
    new_mei = [m for m in tgt.meis.values() if m["manufacturerPartNumber"] == "AJ MEI PP 100"]
    check(len(tgt.meis) == 2 and len(new_mei) == 1 and new_mei[0]["manufacturer"] == "Hi-Tech Supplier", "one MEI created, none duplicated")
    q = {(x["target"]["id"], x["contexts"][0]["id"], x["preferred"]) for x in tgt.quals}
    check(q == {(new_mei[0]["id"], tc, "TRUE"), (existing_mei, tc, "FALSE")} and len(tgt.quals) == 2,
          "Manufacturing Equivalent Qualifications on the copied part, preferred kept, no duplicates after the retry")
    cab = [x for x in v["rows"][0]["assoc"] if x["kind"] == "changeActions"]
    check(cab and cab[0]["status"] == "pending" and "waiting" in cab[0]["note"], "change actions left pending until the spec is in")
    check(v["verification"]["associations"] == [], "associations read back from the target (%s)" % v["verification"].get("associations"))
    check(len(tgt.inst[ta]) == 4 and len(tgt.inst[tb]) == 3, "the structure itself is copied as before")

    # ---------------------------------------------------------------- run again: nothing duplicated
    before = (len(tgt.docs), len(tgt.meis), len(tgt.quals), sum(len(x) for x in tgt.resp.values()))
    call("POST", "/execute", {"run": run})
    wait(run)
    after = (len(tgt.docs), len(tgt.meis), len(tgt.quals), sum(len(x) for x in tgt.resp.values()))
    check(before == after, "running the copy again duplicates nothing %s -> %s" % (before, after))

    httpd.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
