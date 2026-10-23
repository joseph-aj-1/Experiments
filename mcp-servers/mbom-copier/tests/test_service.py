"""Tests for mbom_service.py: real HTTP on 127.0.0.1 against an in-memory target tenant.

    python tests/test_service.py
"""
from __future__ import annotations

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
import mbom_copy  # noqa: E402
import mbom_service as svc  # noqa: E402
from test_copy import Tenant, make_source, check, fails  # noqa: E402

TMP = Path(tempfile.mkdtemp())
mbom_copy.RETRY_DELAY = 0.01
mbom_copy.RUNS = TMP / "runs"
svc.TARGET_ENV = TMP / "target.env"
svc.CONFIG = TMP / "service.json"
ORIGIN = "https://r1132100000770-us1-ifwe.3dexperience.3ds.com"


def source_payload(src: Tenant, root: str) -> dict:
    """What the widget sends: every item and the raw instance lists, as read with WAFData."""
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
    cfg = svc.load_config()
    token = cfg["token"]
    tgt = Tenant("R1132100000770")
    engine = svc.Engine(target_factory=tgt.client)
    httpd = svc.serve(engine, port=0, cfg=cfg)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def call(method, path, body=None, tok=token, origin=ORIGIN, raw=False):
        req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None)
        req.add_header("Content-Type", "application/json")
        if tok is not None:
            req.add_header("X-MBC-Token", tok)
        if origin:
            req.add_header("Origin", origin)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, (dict(r.headers) if raw else json.loads(r.read() or b"null"))
        except urllib.error.HTTPError as e:
            return e.code, (dict(e.headers) if raw else json.loads(e.read() or b"null"))

    # --- security
    check(httpd.server_address[0] == "127.0.0.1", "listens on 127.0.0.1 only")
    code, _ = call("GET", "/status", tok=None)
    check(code == 401, "no pairing token -> 401")
    code, _ = call("GET", "/status", tok="wrong")
    check(code == 401, "wrong pairing token -> 401")
    code, body = call("GET", "/status", origin="https://evil.example.com")
    check(code == 403 and "allowed_origins" in body["error"], "foreign web page (Origin) -> 403")
    code, hdrs = call("OPTIONS", "/plan", origin=ORIGIN, tok=None, raw=True)
    check(code == 204 and hdrs.get("Access-Control-Allow-Origin") == ORIGIN and hdrs.get("Access-Control-Allow-Private-Network") == "true"
          and "X-MBC-Token" in hdrs.get("Access-Control-Allow-Headers", ""), "CORS + private-network preflight for 3DEXPERIENCE pages")
    code, hdrs = call("OPTIONS", "/plan", origin="https://joseph-aj-1.github.io", tok=None, raw=True)
    check(hdrs.get("Access-Control-Allow-Origin") == "https://joseph-aj-1.github.io", "widget's GitHub Pages origin allowed")
    code, hdrs = call("OPTIONS", "/plan", origin="https://evil.example.com", tok=None, raw=True)
    check("Access-Control-Allow-Origin" not in hdrs, "no CORS grant for other origins")

    # --- settings
    code, st = call("GET", "/status")
    check(code == 200 and st["target"]["configured"] is False, "status: target not configured yet")
    code, s = call("POST", "/settings", {"tenant_url": "https://r1132100000770-us1-ifwe.3dexperience.3ds.com/", "username": "hjh",
                                         "password": "p#ss 'w$rd\\x", "api_key": "KEY-123", "security_context": "VPLMProjectLeader.Company Name.Common Space"})
    check(code == 200 and s["tenant"] == "R1132100000770" and s["apigateway_url"] == "https://r1132100000770-us1-apigateway.3dexperience.3ds.com"
          and s["base_url"] == "https://r1132100000770-us1-space.3dexperience.3ds.com/enovia", "tenant URLs derived from the dashboard address")
    check(s["has_password"] and s["has_api_key"] and "password" not in json.dumps(s).lower().replace("has_password", ""),
          "settings reply says a password/key is stored but never returns them")
    env = svc.read_env(svc.TARGET_ENV)
    check(env["TDX_PASSWORD"] == "p#ss 'w$rd\\x" and env["APIKey"] == "KEY-123", "password with # ' $ \\ and space survives the .env round trip")
    call("POST", "/settings", {"username": "hjh2", "password": "", "api_key": ""})
    env = svc.read_env(svc.TARGET_ENV)
    check(env["TDX_PASSWORD"] == "p#ss 'w$rd\\x" and env["APIKey"] == "KEY-123" and env["TDX_USERNAME"] == "hjh2",
          "blank password/key fields keep the stored values")
    code, s = call("POST", "/settings", {"tenant_url": "not a tenant"})
    check(code == 400, "bad tenant address refused")
    code, t = call("POST", "/settings/test")
    check(code == 200 and t["ok"] and t["tenant"] == "R1132100000770", "test connection")
    code, st = call("GET", "/status")
    check(st["target"]["configured"], "status: target configured")

    # --- plan from widget data
    src, a = make_source()
    code, plan = call("POST", "/plan", source_payload(src, a))
    check(code == 200 and plan["counts"]["create"] == 5 and plan["counts"]["inst_create"] == 7 and tgt.writes == 0,
          "plan from the widget's data: 5 items / 7 instances, nothing written (%s)" % (plan.get("counts") or plan))
    rows = plan["rows"]
    check(rows[0]["level"] == 0 and rows[0]["title"] == "AJ MA 101" and any(r["repeat"] for r in rows)
          and all(r["action"] == "create" for r in rows), "plan rows: tree order, repeats marked, actions")
    glue = [r for r in rows if r["title"] == "Glue" and r["level"] == 1][0]
    check(glue["quantity"] == {"magnitude": "LENGTH", "inputValue": "0.5", "inputUnit": "METER"}, "rows carry the instance quantity")
    bad = source_payload(src, a)
    bad["children"].pop(a)
    code, err = call("POST", "/plan", bad)
    check(code == 400 and "were not read" in err["error"], "incomplete widget data refused")

    # --- execute with a failure, then retry
    run = plan["run"]
    tgt.fail_after = 3
    code, v = call("POST", "/execute", {"run": run})
    check(code == 200, "execute starts in the background")
    for _ in range(600):
        code, v = call("GET", f"/runs/{run}")
        if v["status"] != "running":
            break
        time.sleep(0.05)
    check(v["status"] == "incomplete" and any("FAILED" in e for e in v["events"]), "failed steps reported (%s)" % v["status"])
    tgt.fail_after = None
    call("POST", "/execute", {"run": run})
    for _ in range(600):
        code, v = call("GET", f"/runs/{run}")
        if v["status"] != "running":
            break
        time.sleep(0.05)
    check(v["status"] == "done" and v["verification"]["problems"] == [], "retry finishes the copy and verifies (%s)" % v["status"])
    check(len(tgt.items) == 5, "no duplicates after the retry (%d items)" % len(tgt.items))
    check(all(r["action"] == "done" for r in v["rows"]) and all(r.get("instance_status", "done") == "done" for r in v["rows"]),
          "every row shows done")
    code, rl = call("GET", "/runs")
    check(rl and rl[0]["run"] == run and rl[0]["title"] == "AJ MA 101", "runs list")
    code, e = call("POST", "/execute", {"run": "../../etc/passwd"})
    check(code == 400, "run ids can't escape the runs folder")

    httpd.shutdown()
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{'ALL PASSED' if not fails else str(len(fails)) + ' FAILED'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
