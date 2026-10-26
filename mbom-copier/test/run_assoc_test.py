"""End-to-end test of copying associated objects with the widget: a mocked dashboard plays
the source (with specifications, plants, MEIs and change actions on its items), the real
local service runs against an in-memory target with every web service involved, and
Chromium drives the widget: tick the options, preview, dry run, copy.

    python test/run_assoc_test.py
"""
import base64
import json
import pathlib
import shutil
import sys
import tempfile
import threading

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE.parent
TOOL = APP.parent / "mcp-servers" / "mbom-copier"
sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(TOOL / "tests"))
import assoc as ax  # noqa: E402
import mbom_copy  # noqa: E402
import mbom_service as svc  # noqa: E402
from mock_target import FullTenant  # noqa: E402
from test_copy import make_source  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp())
mbom_copy.RUNS = TMP / "runs"
mbom_copy.RETRY_DELAY = 0.01
svc.TARGET_ENV = TMP / "target.env"
svc.CONFIG = TMP / "service.json"
PAGES = "https://joseph-aj-1.github.io/Experiments/mbom-copier/"
FCS_SRC = "https://eu1-demo-dfcs.3dexperience.3ds.com/"
PDF = b"%PDF-1.4 spec of AJ MA 400 " + bytes(range(256)) * 300

fails = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


# ------------------------------------------------------------------ source with associations
src, root = make_source()
by = {v["title"]: k for k, v in src.items.items()}
a, b, c = root, by["AJ MA 100"], by["AJ PP 100"]
SPACE = "https://oi000629352-eu1-demo-space.3dexperience.3ds.com/enovia"


def doc(did, title, fid, fname, size):
    return {"id": did, "type": "Document", "dataelements": {"name": "DOC-" + did, "title": title, "revision": "0", "description": title + " desc",
            "stateNLS": "In Work", "hasDownloadAccess": "TRUE"},
            "relateddata": {"files": [{"id": fid, "dataelements": {"title": fname, "fileSize": str(size)}}]}}


ASSOC = {
    "docs": {a: [doc("D1", "00753-2350", "F1", "00753-2350.pdf", len(PDF))], b: [doc("D1", "00753-2350", "F1", "00753-2350.pdf", len(PDF))]},
    "resp": {b: [{"id": "R1", "type": "DELMfgResponsibilityCnx", "makeOrBuy": "Make",
                  "organizationRef": {"identifier": "ORGPUNE", "type": "Plant", "relativePath": "/resources/v1/modeler/organizations/ORGPUNE"}}],
             c: [{"id": "R2", "type": "DELMfgResponsibilityCnx", "makeOrBuy": "Buy",
                  "organizationRef": {"identifier": "ORGXYZ", "type": "Plant", "relativePath": "/resources/v1/modeler/organizations/ORGXYZ"}}]},
    "orgs": {"ORGPUNE": {"id": "ORGPUNE", "title": "Pune"}, "ORGXYZ": {"id": "ORGXYZ", "title": "Lyon"}},
    "impact": {a: [{"impactType": "PROPOSED", "referencedObject": {"identifier": "CA77", "type": "Change Action",
                                                                   "relativePath": "/resources/v1/modeler/dslc/changeaction/CA77"}}]},
    "cc": {a: "ID"},
    "capc": {"CA77": [{"internalid": "P1", "target": "CurrentVersion", "where": {"identifier": a, "type": "CreateAssembly"},
                       "whats": [{"internalid": "W1", "what": "ChangeMaturityRelease"}]}]},
    "cas": {"CA77": {"id": "CA77", "name": "CA-00000077", "title": "Introduce AJ MA 400", "description": "test", "severity": "Low", "state": "In Work"}},
    "quals": [{"id": "Q1", "name": "MQ-100000", "type": "SRC Manufacturing Equivalent Qualification", "state": "In Work",
               "preferred": "TRUE", "approved": "Yes", "target": {"id": "MEIX", "type": "Physical Product"},
               "contexts": [{"id": c, "relativePath": "/resources/v1/modeler/dsmfg/dsmfg:MfgItem/" + c}]}],
    "meis": {"MEIX": {"id": "MEIX", "title": "AJ MEI PP 100", "name": "prd-OI000629352-00000002", "manufacturer": "Hi-Tech Supplier",
                      "manufacturerPartNumber": "AJ MEI PP 100"}},
}

# ------------------------------------------------------------------ target + service
tgt = FullTenant("R1132100000770")
tgt.add_plant("Pune")

cfg = svc.load_config()
httpd = svc.serve(svc.Engine(target_factory=tgt.client, space_url=tgt.space, fcs_client=tgt.fcs_client()), port=0, cfg=cfg)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
SVC = f"http://127.0.0.1:{httpd.server_address[1]}"
svc.write_target({"tenant_url": "https://r1132100000770-us1-ifwe.3dexperience.3ds.com/", "username": "hjh",
                  "password": "x", "security_context": "A.B.C"})

html = (APP / "index.html").read_text(encoding="utf-8")
mock = (HERE / "mock_platform.js").read_text()
data = "window.__SRC = " + json.dumps({"tenant": src.tid, "items": src.items, "inst": src.inst, "assoc": ASSOC}) + ";"
harness = html.replace("\n<body>", "\n<body><script>" + data + mock + "</script>", 1)

with sync_playwright() as p:
    b_ = p.chromium.launch()
    ctx = b_.new_context(viewport={"width": 1200, "height": 1000})
    ctx.grant_permissions(["local-network-access"], origin="https://joseph-aj-1.github.io")
    ctx.add_init_script("try{localStorage.setItem('mbc.service',%r);localStorage.setItem('mbc.token',%r)}catch(e){}" % (SVC, cfg["token"]))

    def pages(route):
        path = route.request.url.split(PAGES, 1)[-1].split("?", 1)[0]
        if path == "harness.html":
            return route.fulfill(status=200, body=harness, headers={"Content-Type": "text/html"})
        f = APP / path
        if not f.is_file():
            return route.fulfill(status=404, body="not found")
        ct = {"js": "application/javascript", "css": "text/css", "json": "application/json"}.get(f.suffix[1:], "application/octet-stream")
        route.fulfill(status=200, body=f.read_bytes(), headers={"Access-Control-Allow-Origin": "*", "Content-Type": ct})
    ctx.route(PAGES + "**", pages)
    fcs_hits = []

    def fcs(route):
        fcs_hits.append(route.request.url)
        route.fulfill(status=200, body=PDF, headers={"Access-Control-Allow-Origin": "*", "Content-Type": "application/octet-stream"})
    ctx.route(FCS_SRC + "**", fcs)
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(PAGES + "harness.html")
    pg.wait_for_function("document.querySelector('.svc') && document.querySelector('.svc').className.indexOf('ok') >= 0", timeout=10000)

    labels = pg.evaluate("Array.from(document.querySelectorAll('.opts.assoc label')).map(function(l){return l.textContent.trim()})")
    check(labels == ["Change Actions", "Plants", "MEIs", "Specifications"], "four association options offered (%s)" % labels)

    # drop with nothing ticked: no Associated column, no association reads
    pg.evaluate("window.__drop({ data: { items: [{ objectId: '%s', displayName: 'AJ MA 101', envId: 'OI000629352' }] } })" % a)
    pg.wait_for_function("document.querySelector('.status').textContent.indexOf('Next: Dry run') >= 0", timeout=8000)
    check(pg.evaluate("document.querySelectorAll('table.bom thead th').length") == 7, "nothing ticked: no Associated column")
    check(not any("parentId" in c_["path"] or "Responsibility" in c_["path"] for c_ in pg.evaluate("window.__calls")), "nothing ticked: no association reads")

    # tick all four: they are read and shown in the preview
    for lab in labels:
        pg.check(f".opts.assoc label:has-text('{lab}') input")
    pg.wait_for_function("document.querySelector('.assocnote').textContent.indexOf('Specifications: 1 on 2') >= 0 && "
                         "document.querySelector('.assocnote').textContent.indexOf('reading') < 0", timeout=10000)
    note = pg.inner_text(".assocnote")
    check("Change Actions: 1 on 1 item" in note and "Plants: 2 on 2 items" in note and "MEIs: 1 on 1 item" in note and "Specifications: 1 on 2 items" in note, "counts per kind (%s)" % note)
    cells = pg.evaluate("Array.from(document.querySelectorAll('table.bom tbody tr:not(.errline)')).map(function(r){return [r.cells[1].textContent.trim(), r.querySelector('td.assoc') ? r.querySelector('td.assoc').textContent.trim() : null]})")
    row = {t: x for t, x in cells}
    check("CA CA-00000077 Introduce AJ MA 400 (proposed)" in row["AJ MA 101"] and "Spec 00753-2350 — 00753-2350.pdf" in row["AJ MA 101"],
          "top item shows its change action and specification (%s)" % row["AJ MA 101"])
    check("Plant Pune (Make)" in row["└─AJ MA 100"], "plant name and Make/Buy shown (%s)" % row["└─AJ MA 100"])
    pp = [x for t, x in cells if t == "└─AJ PP 100" and x][0]
    check("MEI Hi-Tech Supplier · AJ MEI PP 100 (preferred)" in pp and "Plant Lyon (Buy)" in pp, "MEI with manufacturer and part number (%s)" % pp)
    check(not any(c_["method"] != "GET" and "CSRF" not in c_["path"] and "contextLocate" not in c_["path"]
                  for c_ in pg.evaluate("window.__calls")), "source: only reads (plus the Sourcing lookup)")
    saved = pg.evaluate("localStorage.getItem('mbc.assoc')")
    check(json.loads(saved) == {"changeActions": True, "plants": True, "meis": True, "specs": True}, "ticked options remembered in this browser")

    # dry run: plan per association
    pg.click(".btn.go:text('Dry run')")
    pg.wait_for_function("document.querySelector('.status').textContent.indexOf('Dry run done') === 0", timeout=10000)
    summ = pg.inner_text(".summary")
    check("1 new document" in summ and "1 new MEI" in summ and "1 new change action" in summ, "summary counts new documents, MEIs and CAs (%s)" % summ)
    check("Lyon" in summ and "API spec" not in summ.split("Plant links")[0], "warnings: missing plant only (%s)" % summ)
    badges = pg.evaluate("Array.from(document.querySelectorAll('.badge')).map(function(b){return b.className + ' | ' + b.textContent})")
    check(any("k-plants" in x and "s-missing" in x and "Lyon" in x for x in badges), "Lyon marked missing in target")
    check(any("k-plants" in x and "Pune" in x and "link" in x for x in badges), "Pune will be linked")
    check(tgt.writes == 0, "dry run wrote nothing to the target")

    # copy: spec file carried from source to service to target
    pg.click(".btn.danger")
    pg.click(".btn.danger")
    pg.wait_for_function("document.querySelector('.status').textContent.indexOf('Copied:') === 0 || "
                         "document.querySelector('.status').className.indexOf('error') >= 0", timeout=30000)
    st = pg.inner_text(".status")
    check(st.startswith("Copied:"), "copy finished (%s)" % st)
    check(len(fcs_hits) == 1, "spec file downloaded once from the source file server (%d)" % len(fcs_hits))
    t = {it["title"]: k for k, it in tgt.items.items()}
    d = list(tgt.docs.values())
    check(len(d) == 1 and d[0]["files"][0]["bytes"] == PDF and d[0]["parents"] == {t["AJ MA 101"], t["AJ MA 100"]},
          "document with its file created once in the target and attached to both items")
    check([(k, l["organizationRef"]["identifier"]) for k, ls in tgt.resp.items() for l in ls] == [(t["AJ MA 100"], list(tgt.plants)[0])],
          "Pune linked; Lyon skipped")
    check(len(tgt.meis) == 1 and tgt.quals and tgt.quals[0]["contexts"][0]["id"] == t["AJ PP 100"] and tgt.quals[0]["preferred"] == "TRUE",
          "MEI created and qualified on the copied part, preferred kept")
    done = pg.evaluate("document.querySelectorAll('.badge.s-done').length")
    check(done == 5, "badges show done: spec x2, plant, MEI, CA (%d)" % done)
    check(len(tgt.cas) == 1 and [pc["where"]["identifier"] for pc in list(tgt.cas.values())[0]["proposedChanges"]] == [t["AJ MA 101"]],
          "change action created with the copied top item as proposed change")
    check(list(tgt.cas.values())[0]["proposedChanges"][0]["whats"] == [{"what": "ChangeMaturityRelease"}],
          "release activity read from the source CA and copied")
    check(getattr(tgt, "cc", {}) == {t["AJ MA 101"]: "ANY"}, "change control switched on for the top item, as in the source")
    pg.screenshot(path=str(HERE / "shot_assoc.png"), full_page=True)
    check(not errors, "no page errors %s" % errors)
    b_.close()

httpd.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}")
sys.exit(1 if fails else 0)
