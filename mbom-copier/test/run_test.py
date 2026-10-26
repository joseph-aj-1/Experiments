"""End-to-end test of the MBOM Copier widget.

A mocked 3DDashboard plays the source tenant; the real local service (mbom_service.py)
runs on 127.0.0.1 against an in-memory target tenant; Chromium drives the widget.

    pip install playwright && python -m playwright install chromium
    python test/run_test.py
"""
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
import mbom_copy  # noqa: E402
import mbom_service as svc  # noqa: E402
from test_copy import Tenant, make_source  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

TMP = pathlib.Path(tempfile.mkdtemp())
mbom_copy.RUNS = TMP / "runs"
mbom_copy.RETRY_DELAY = 0.01
svc.TARGET_ENV = TMP / "target.env"
svc.CONFIG = TMP / "service.json"
PAGES = "https://joseph-aj-1.github.io/Experiments/mbom-copier/"

fails = []


def check(cond, msg):
    print(("PASS " if cond else "FAIL ") + msg)
    if not cond:
        fails.append(msg)


# source data (same as the Python tests) and a real service against a mock target
src, root = make_source()
tgt = Tenant("R1132100000770")
cfg = svc.load_config()
httpd = svc.serve(svc.Engine(target_factory=tgt.client), port=0, cfg=cfg)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
SVC = f"http://127.0.0.1:{httpd.server_address[1]}"

html = (APP / "index.html").read_text(encoding="utf-8")
mock = (HERE / "mock_platform.js").read_text()
data = "window.__SRC = " + json.dumps({"tenant": src.tid, "items": src.items, "inst": src.inst}) + ";"
harness = html.replace("\n<body>", "\n<body><script>" + data + mock + "</script>", 1)
assert mock in harness

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": 900, "height": 1000})
    # what the user does once at Chrome's "access devices on your local network" prompt
    ctx.grant_permissions(["local-network-access"], origin="https://joseph-aj-1.github.io")

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
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(PAGES + "harness.html")
    pg.wait_for_function("document.querySelector('.status') && document.querySelector('.status').textContent.indexOf('Ready') === 0", timeout=8000)
    check("Source: OI000629352" in pg.inner_text(".conn"), "source tenant and context shown")

    # --- service not paired yet (default address is not where the test service runs)
    pg.wait_for_function("document.querySelector('.svc').className.indexOf('bad') >= 0", timeout=8000)
    check("Service not running" in pg.inner_text(".svc"), "no service at the default address -> 'Service not running'")
    check(pg.get_attribute(".btn.go:text('Dry run')", "aria-disabled") == "true", "Dry run disabled without an item and a service")

    # --- preview: drop the top item
    pg.evaluate("window.__drop({ protocol: '3DXContent', data: { items: [{ objectId: '%s', displayName: 'AJ MA 101', envId: 'OI000629352' }] } })" % root)
    pg.wait_for_selector("table.bom")
    pg.wait_for_function("document.querySelector('.status').textContent.indexOf('Next: Dry run') >= 0", timeout=8000)
    rows = pg.evaluate("Array.from(document.querySelectorAll('table.bom tbody tr:not(.errline)')).map(function(r){return Array.from(r.cells).map(function(c){return c.textContent.trim()})})")
    check(len(rows) == 8 and rows[0][1] == "AJ MA 101" and rows[0][0] == "0", "preview shows the whole tree right after the drop (%d rows)" % len(rows))
    check(any("(same item as above)" in r[1] for r in rows), "shared items marked in the preview")
    glue = [r for r in rows if r[1].startswith("└─Glue") and r[0] == "1"]
    check(glue and glue[0][3] == "0.5 m", "continuous quantity shown in the preview (%s)" % (glue[0][3] if glue else None))
    check(pg.evaluate("document.querySelectorAll('table.bom thead th').length") == 7, "preview has no Action/Target columns yet")
    check("AJ MA 101: 5 items, 7 instances" in pg.inner_text(".status"), "status counts items and instances")
    check(all(c["method"] == "GET" for c in pg.evaluate("window.__calls")), "only GETs against the source tenant")

    # --- settings: pair, configure target, test
    pg.click(".gear")
    pg.fill("[name=service]", SVC)
    pg.fill("[name=token]", "wrong-token")
    pg.click("[data-act=svc-save]")
    pg.wait_for_function("document.querySelector('.sstat').textContent.length > 0 && document.querySelector('.sstat').textContent.indexOf('Checking') < 0")
    check("pairing token" in pg.inner_text(".sstat").lower(), "wrong token -> clear message")
    pg.fill("[name=token]", cfg["token"])
    pg.click("[data-act=svc-save]")
    pg.wait_for_function("document.querySelector('.sstat').textContent.indexOf('reached') >= 0", timeout=8000)
    check("Now fill in the target" in pg.inner_text(".sstat"), "service reached; target not set up yet")
    pg.fill("[name=tenant_url]", "https://r1132100000770-us1-ifwe.3dexperience.3ds.com/")
    pg.fill("[name=username]", "hjh")
    pg.fill("[name=password]", "s3cret #pass")
    pg.fill("[name=security_context]", "VPLMProjectLeader.Company Name.Common Space")
    pg.fill("[name=api_key]", "AGENT-KEY")
    pg.click("[data-act=tgt-test]")
    pg.wait_for_function("document.querySelector('.sstat').textContent.indexOf('Connected') >= 0", timeout=8000)
    check("Connected to R1132100000770" in pg.inner_text(".sstat"), "test connection from Settings")
    env = svc.read_env(svc.TARGET_ENV)
    check(env["TDX_PASSWORD"] == "s3cret #pass" and env["APIKey"] == "AGENT-KEY" and env["TDX_TENANT"] == "R1132100000770",
          "Settings wrote target.env on the PC")
    check(pg.input_value("[name=password]") == "" and "stored" in pg.get_attribute("[name=password]", "placeholder"),
          "password field cleared after saving; shows 'stored'")
    stored = pg.evaluate("JSON.stringify(window.localStorage)")
    check("s3cret" not in stored and "AGENT-KEY" not in stored and cfg["token"] in stored, "browser keeps only the service address/token, no secrets")
    check("s3cret" not in json.dumps(pg.evaluate("window.widget.getValue('x')") or ""), "nothing secret in widget preferences")
    pg.click("[data-act=close]")
    check("Target: R1132100000770 (hjh)" in pg.inner_text(".svc"), "bar shows the configured target")

    # --- dry run
    pg.click(".btn.go:text('Dry run')")
    pg.wait_for_function("document.querySelector('.status').textContent.indexOf('Dry run done') === 0", timeout=10000)
    check("To create in R1132100000770: 5 items, 7 instances" in pg.inner_text(".summary"), "dry run summary")
    check(tgt.writes == 0, "dry run wrote nothing to the target")
    acts = pg.evaluate("Array.from(document.querySelectorAll('table.bom tbody tr td.act')).map(function(c){return c.textContent})")
    check(acts and acts[0] == "Create" and "Create" in acts, "Action column after the dry run")

    # --- copy (two clicks)
    copy = pg.locator(".btn.danger")
    check(copy.get_attribute("aria-disabled") == "false" and "Copy to R1132100000770" in copy.inner_text(), "Copy enabled after a dry run")
    copy.click()
    check("Click again to create 5 items, 7 instances in R1132100000770" in copy.inner_text() and tgt.writes == 0, "first click only arms Copy")
    copy.click()
    pg.wait_for_function("document.querySelector('.status').textContent.indexOf('Copied:') === 0", timeout=20000)
    check("matches the source" in pg.inner_text(".status"), "copy finished and verified")
    acts = pg.evaluate("Array.from(document.querySelectorAll('table.bom tbody tr:not(.errline)')).filter(function(r){return r.querySelector('td.act').textContent}).map(function(r){return r.querySelector('td.act').textContent})")
    check(acts and all(a == "Done" for a in acts), "every row shows Done")
    rootrec = [k for k, v in tgt.items.items() if v["title"] == "AJ MA 101"]
    check(len(tgt.items) == 5 and len(rootrec) == 1 and len(tgt.tree(rootrec[0])) == len(src.tree(root)), "target has the full structure")
    check("created AJ MA 101" in pg.inner_text(".log"), "progress log shown")
    check(pg.get_attribute(".btn.danger", "aria-disabled") == "true", "Copy disabled once done")
    pg.screenshot(path=str(HERE / "shot_copied.png"), full_page=True)

    # --- changing an option invalidates the plan
    pg.fill(".suf input", " (copy)")
    check("run the dry run again" in pg.inner_text(".status") and pg.evaluate("document.querySelectorAll('table.bom thead th').length") == 7,
          "changing options clears the old plan")

    # --- search path
    pg.fill(".bar input", "AJ MA 100")
    pg.click(".btn.go:text('Search')")
    pg.wait_for_function("document.querySelector('.status').textContent.indexOf('AJ MA 100:') === 0", timeout=8000)
    check(pg.evaluate("document.querySelectorAll('table.bom tbody tr').length") == 4, "search by exact title loads that item's tree")
    pg.screenshot(path=str(HERE / "shot.png"), full_page=True)
    check(not errors, "no page errors %s" % errors)
    b.close()

httpd.shutdown()
shutil.rmtree(TMP, ignore_errors=True)
print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}")
sys.exit(1 if fails else 0)
