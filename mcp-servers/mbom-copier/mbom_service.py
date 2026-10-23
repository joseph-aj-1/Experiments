"""Local service behind the MBOM Copier widget.

    python mbom_service.py            # listens on http://127.0.0.1:8765

The widget (in your 3DDashboard) reads the source MBOM with your dashboard sign-in and
sends it here; this service plans and creates the copy in the target tenant with the
same code as mbom_copy.py. The target connection lives in target.env on this PC: the
widget's Settings screen writes it, and no password or agent key is ever sent back.

Safety:
  * listens on 127.0.0.1 only (not reachable from other machines)
  * every call needs the pairing token printed at start-up (kept in service.json)
  * calls must come from a 3DEXPERIENCE page or the widget's own site (Origin check)
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import mbom_copy as mc

VERSION = "1.0"
ROOT = mc.ROOT
CONFIG = ROOT / "service.json"
TARGET_ENV = ROOT / "target.env"
DEFAULT_ORIGINS = [r"https://([a-z0-9-]+\.)*3dexperience\.3ds\.com", r"https://joseph-aj-1\.github\.io"]
log = logging.getLogger("mbom_service")


# --------------------------------------------------------------------------- config
def load_config() -> dict:
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    changed = False
    if not cfg.get("token"):
        cfg["token"] = secrets.token_urlsafe(18)
        changed = True
    cfg.setdefault("port", 8765)
    cfg.setdefault("allowed_origins", DEFAULT_ORIGINS)
    if changed or not CONFIG.exists():
        CONFIG.write_text(json.dumps(cfg, indent=1))
    return cfg


def origin_ok(origin: str, cfg: dict) -> bool:
    return any(re.fullmatch(p, origin or "") for p in cfg["allowed_origins"])


# --------------------------------------------------------------------------- target.env
ENV_KEYS = ["TDX_USERNAME", "TDX_PASSWORD", "SecurityContext", "APIKey", "TDX_APIGATEWAY_URL", "TDX_BASE_URL",
            "TDX_TENANT", "TDX_SERVER_PREFERENCE", "TDX_VERIFY_SSL", "TDX_TIMEOUT_SECONDS"]
SECRET_KEYS = {"TDX_PASSWORD", "APIKey"}
_HOST = re.compile(r"^(?P<t>(?:oi|r)\d{6,})-(?P<rest>.+?)-(?:ifwe|space|apigateway|3dswym|3ddashboard|3dpassport|"
                   r"fedsearch|3dcompass|usersgroup|sourcing|3dnotification)\.(?P<dom>3dexperience\.3ds\.com)$", re.I)


def read_env(path: Path | None = None) -> dict:
    from dotenv import dotenv_values
    path = path or TARGET_ENV
    return {k: (v or "") for k, v in dotenv_values(path).items()} if path.exists() else {}


def env_line(k: str, v: str) -> str:
    v = str(v)
    if v and (re.search(r"[\s#'\"\\$]", v)):          # quote anything dotenv could misread
        return f"{k}='" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
    return f"{k}={v}"


def tenant_urls(url_or_id: str) -> dict:
    """Any address of a tenant (dashboard, 3DSpace, gateway) -> tenant id + gateway + 3DSpace URLs."""
    host = urlparse(url_or_id if "//" in url_or_id else "https://" + url_or_id).hostname or ""
    m = _HOST.match(host)
    if not m:
        raise mc.CopyError("Paste an address of the target tenant, e.g. https://r1132100000770-us1-ifwe.3dexperience.3ds.com/")
    pre = f"{m.group('t').lower()}-{m.group('rest').lower()}"
    return {"TDX_TENANT": m.group("t").upper(),
            "TDX_APIGATEWAY_URL": f"https://{pre}-apigateway.{m.group('dom')}",
            "TDX_BASE_URL": f"https://{pre}-space.{m.group('dom')}/enovia"}


def write_target(update: dict) -> dict:
    env = read_env()
    if update.get("tenant_url"):
        env.update(tenant_urls(update["tenant_url"]))
    for field, key in (("username", "TDX_USERNAME"), ("security_context", "SecurityContext"),
                       ("server_preference", "TDX_SERVER_PREFERENCE")):
        if field in update and update[field] is not None:
            env[key] = str(update[field]).strip()
    for field, key in (("password", "TDX_PASSWORD"), ("api_key", "APIKey")):
        if update.get(field):                        # blank = keep what is stored
            env[key] = update[field]
    if update.get("clear_api_key"):
        env["APIKey"] = ""
    env.setdefault("TDX_SERVER_PREFERENCE", "APIGateway")
    env.setdefault("TDX_VERIFY_SSL", "true")
    env.setdefault("TDX_TIMEOUT_SECONDS", "60")
    lines = ["# TARGET tenant for MBOM Copier. Written by the widget's Settings screen; you can also edit it by hand.",
             "# Stays on this PC; never commit or share it."]
    lines += [env_line(k, env.get(k, "")) for k in ENV_KEYS]
    lines += [env_line(k, v) for k, v in env.items() if k not in ENV_KEYS]
    TARGET_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target_summary()


def target_summary() -> dict:
    env = read_env()
    return {"configured": bool(env.get("TDX_TENANT") and env.get("TDX_USERNAME") and env.get("TDX_PASSWORD")
                               and env.get("SecurityContext")),
            "tenant": env.get("TDX_TENANT", ""), "apigateway_url": env.get("TDX_APIGATEWAY_URL", ""),
            "base_url": env.get("TDX_BASE_URL", ""), "username": env.get("TDX_USERNAME", ""),
            "security_context": env.get("SecurityContext", ""),
            "server_preference": env.get("TDX_SERVER_PREFERENCE", "APIGateway"),
            "has_password": bool(env.get("TDX_PASSWORD")), "has_api_key": bool(env.get("APIKey"))}


# --------------------------------------------------------------------------- engine
class Engine:
    """One asyncio loop for the whole service (the 3DPassport login code keeps a single lock)."""

    def __init__(self, target_factory=None):
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True, name="mbom-loop").start()
        self._factory = target_factory           # tests inject a mock client
        self._tgt: mc.Api | None = None
        self.jobs: dict[str, dict] = {}           # run id -> {"thread": Future, "copier": Copier}
        self.lock = threading.Lock()

    def run(self, coro, timeout: float = 600):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def reset_target(self):
        async def close():
            if self._tgt is not None:
                try:
                    await self._tgt.c.aclose()
                except Exception:
                    pass
            self._tgt = None
            try:                                    # forget the old login
                from app import client_factory as cf  # type: ignore
                cf._LOGGED_IN_FOR.clear()
                cf._SHARED_COOKIES.clear()
            except Exception:
                pass
        self.run(close())

    async def target(self) -> mc.Api:
        if self._tgt is None:
            if self._factory:
                c = self._factory()
            else:
                if not TARGET_ENV.exists():
                    raise mc.CopyError("The target is not set up yet: open Settings in the widget.")
                c = mc.make_client(mc.load_profile(TARGET_ENV))
            self._tgt = mc.Api(c, c.tenant_id)
        return self._tgt

    # ------------------------------------------------------------- operations
    async def test(self) -> dict:
        tgt = await self.target()
        await tgt.search("MBOM Copier connection test", 1)
        return {"ok": True, "tenant": tgt.tenant}

    async def plan(self, body: dict) -> dict:
        tgt = await self.target()
        if body.get("run"):
            cp = self.copier(body["run"])
            if self.busy(cp):
                return self.view(cp)
        else:
            src = (body.get("source_tenant") or "").upper()
            if not src or not body.get("root") or not isinstance(body.get("items"), dict):
                raise mc.CopyError("send source_tenant, root, items and children")
            tree = mc.build_tree(body["root"], body["items"], body.get("children") or {}, src)
            cp = mc.Copier.new(src, tgt, tree, bool(body.get("reuse_existing")), body.get("title_suffix") or "", quiet=True)
        cp.tgt = tgt
        await cp.check_target()
        cp.rec["status"] = cp.rec.get("status") if cp.rec.get("status") not in (None, "running") else "planned"
        cp.save()
        return self.view(cp)

    def copier(self, run: str) -> mc.Copier:
        job = self.jobs.get(run)
        if job:
            return job["copier"]
        path = self.run_path(run)
        rec = json.loads(path.read_text())
        return mc.Copier(rec["source"], self._tgt, rec, path, quiet=True)

    @staticmethod
    def run_path(run: str) -> Path:
        if not re.fullmatch(r"[\w.-]+", run or ""):
            raise mc.CopyError("bad run id")
        p = mc.RUNS / f"{run}.json"
        if not p.exists():
            raise mc.CopyError(f"run {run} not found")
        return p

    def busy(self, cp: mc.Copier) -> bool:
        job = self.jobs.get(cp.path.stem)
        return bool(job and not job["future"].done())

    def start(self, run: str) -> dict:
        with self.lock:
            if any(not j["future"].done() for j in self.jobs.values()):
                raise mc.CopyError("another copy is running; wait for it to finish")
            cp = self.copier(run)
            if not cp.rec.get("checked"):
                raise mc.CopyError("plan the copy first")
            cp.rec["events"] = []

            async def go():
                cp.tgt = await self.target()
                if cp.rec["target"] != cp.tgt.tenant:
                    raise mc.CopyError(f"this run copies to {cp.rec['target']}, but Settings point at {cp.tgt.tenant}")
                await cp.check_target()          # the target may have changed since the plan
                c = cp.counts()
                if not c["create"] and not c["inst_create"]:
                    cp.say("Nothing to create.")
                    await cp.verify()
                    cp.rec["status"] = "done"
                    cp.save()
                    return True
                return await cp.execute()

            fut = asyncio.run_coroutine_threadsafe(go(), self.loop)

            def finished(f):
                exc = f.exception()
                if exc:
                    cp.rec["status"] = "failed"
                    cp.rec["error"] = str(exc)
                    cp.say(f"ERROR: {exc}")
                    cp.save()
            fut.add_done_callback(finished)
            self.jobs[run] = {"future": fut, "copier": cp}
        return self.view(cp)

    def view(self, cp: mc.Copier) -> dict:
        job = self.jobs.get(cp.path.stem)
        running = bool(job and not job["future"].done())
        return {"run": cp.path.stem, "source": cp.rec["source"], "target": cp.rec["target"],
                "status": "running" if running else cp.rec.get("status"), "error": cp.rec.get("error"),
                "options": cp.rec["options"], "counts": cp.counts(), "warnings": cp.warnings(),
                "rows": cp.plan_rows(), "events": cp.rec.get("events", [])[-200:],
                "verification": cp.rec.get("verification")}

    def runs(self) -> list[dict]:
        out = []
        for p in sorted(mc.RUNS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]:
            try:
                r = json.loads(p.read_text())
                root = r["tree"]["items"][r["tree"]["root"]]
                out.append({"run": p.stem, "source": r["source"], "target": r["target"], "status": r.get("status"),
                            "title": root.get("title"), "name": root.get("name"), "started": r.get("started")})
            except Exception:
                continue
        return out


# --------------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "MBOMCopier/" + VERSION
    cfg: dict = {}
    engine: Engine

    def log_message(self, fmt, *args):
        log.info("%s %s", self.address_string(), fmt % args)

    def cors(self):
        origin = self.headers.get("Origin", "")
        if origin and origin_ok(origin, self.cfg):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-MBC-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Max-Age", "600")

    def reply(self, code: int, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def allowed(self) -> bool:
        origin = self.headers.get("Origin", "")
        if origin and not origin_ok(origin, self.cfg):
            self.reply(403, {"error": f"Calls from {origin} are not allowed. Add it to allowed_origins in service.json."})
            return False
        if not secrets.compare_digest(self.headers.get("X-MBC-Token", ""), self.cfg["token"]):
            self.reply(401, {"error": "Wrong or missing pairing token. Copy it from the service window into Settings."})
            return False
        return True

    def body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 50_000_000:
            raise mc.CopyError("request too large")
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def route(self, method: str):
        if not self.allowed():
            return
        path = urlparse(self.path).path.rstrip("/")
        e = self.engine
        try:
            if method == "GET" and path == "/status":
                return self.reply(200, {"ok": True, "version": VERSION, "target": target_summary()})
            if method == "GET" and path == "/settings":
                return self.reply(200, target_summary())
            if method == "POST" and path == "/settings":
                s = write_target(self.body())
                e.reset_target()
                return self.reply(200, s)
            if method == "POST" and path == "/settings/test":
                return self.reply(200, e.run(e.test(), 120))
            if method == "POST" and path == "/plan":
                return self.reply(200, e.run(e.plan(self.body())))
            if method == "POST" and path == "/execute":
                return self.reply(200, e.start(self.body().get("run", "")))
            if method == "GET" and path == "/runs":
                return self.reply(200, e.runs())
            m = re.fullmatch(r"/runs/([\w.-]+)", path)
            if method == "GET" and m:
                cp = e.copier(m.group(1))
                return self.reply(200, e.view(cp))
            return self.reply(404, {"error": f"no route {method} {path}"})
        except mc.CopyError as x:
            return self.reply(400, {"error": str(x)})
        except Exception as x:                       # sign-in problems, network, bugs
            name = type(x).__name__
            if name == "PassportLoginError":
                return self.reply(502, {"error": f"Signing in to the target failed: {x}"})
            log.error("%s %s failed:\n%s", method, path, traceback.format_exc())
            return self.reply(500, {"error": f"{name}: {x}"})


def serve(engine: Engine | None = None, port: int | None = None, cfg: dict | None = None) -> ThreadingHTTPServer:
    cfg = cfg or load_config()
    Handler.cfg = cfg
    Handler.engine = engine or Engine()
    httpd = ThreadingHTTPServer(("127.0.0.1", port if port is not None else cfg["port"]), Handler)
    return httpd


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config()
    try:
        httpd = serve(cfg=cfg)
    except OSError as x:
        print(f"Could not listen on 127.0.0.1:{cfg['port']} ({x}). Is the service already running?")
        return 1
    t = target_summary()
    print(f"MBOM Copier service {VERSION} on http://127.0.0.1:{cfg['port']}")
    print(f"Pairing token (paste into the widget's Settings once): {cfg['token']}")
    print(f"Target: {t['tenant'] or 'not set up yet - use Settings in the widget'}")
    print("Leave this window open while you use the widget. Ctrl+C stops it.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
