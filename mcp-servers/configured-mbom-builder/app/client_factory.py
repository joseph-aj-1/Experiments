"""Resolves each OpenAPI spec's `servers` block into a real base URL and
builds the authenticated httpx.AsyncClient used to actually call 3DEXPERIENCE.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

from app.config import Credentials, ServiceEntry


def _resolve_server_url(spec: dict[str, Any], preference: str, creds: Credentials) -> str:
    """Pick the servers[] entry whose template variable matches `preference`
    (e.g. "3DSpace" or "APIGateway") and substitute in the real host.
    """
    servers = spec.get("servers", [])
    if not servers:
        raise ValueError("Spec has no 'servers' block; cannot determine base URL")

    chosen = None
    for server in servers:
        variables = server.get("variables", {})
        if preference in variables:
            chosen = server
            break
    if chosen is None:
        chosen = servers[0]
        variables = chosen.get("variables", {})
    else:
        variables = chosen.get("variables", {})

    url_template = chosen["url"]

    base_is_gateway = "-apigateway." in (httpx.URL(creds.base_url).host or "") if creds.base_url else False
    for var_name, var_def in variables.items():
        if var_name.lower() in ("3dspace",):
            value = creds.base_url
            source = "TDX_BASE_URL"
        elif var_name.lower() in ("apigateway",):
            # Accept the gateway in either variable.
            value = creds.apigateway_url or (creds.base_url if base_is_gateway else "")
            source = "TDX_APIGATEWAY_URL"
        else:
            # Other platform services ({UsersGroup}, {Sourcing}, ...): TDX_<NAME>_URL,
            # else derive from the tenant host the way the service registry names
            # them (<tenant>-<region>-space. -> <tenant>-<region>-usersgroup.).
            env_name = f"TDX_{re.sub(r'[^A-Za-z0-9]', '_', var_name).upper()}_URL"
            value = os.getenv(env_name, "")
            source = env_name
            if not value:
                value = _derive_service_url(var_name, creds)
                if value:
                    logging.getLogger("tdx_mcp.auth").info(
                        "{%s} -> %s (derived from TDX_BASE_URL; set %s to override)", var_name, value, env_name)
            if not value and not _is_placeholder(var_def.get("default", "")):
                value = var_def.get("default", "")
                source = f"spec default for {var_name}"
        if not value:
            raise ValueError(
                f"No URL for '{{{var_name}}}' in the spec's servers block. Set {source} in .env "
                f"(the spec's own default '{var_def.get('default', '')}' is only a placeholder)."
            )
        url_template = url_template.replace(f"{{{var_name}}}", value.rstrip("/"))

    # Guard against any remaining unresolved {placeholder}
    unresolved = re.findall(r"\{([^}]+)\}", url_template)
    if unresolved:
        raise ValueError(
            f"Unresolved server template variables {unresolved} in '{url_template}'. "
            "Set TDX_BASE_URL / TDX_APIGATEWAY_URL in .env."
        )
    return url_template


def _is_placeholder(url: str) -> bool:
    """Spec defaults like 'https://3DEXPERIENCE_UsersGroup' are not real hosts."""
    host = httpx.URL(url).host if url else ""
    return not host or "." not in host or "3dexperience_" in host.lower()


_SERVICE_HOST = re.compile(r"^(?P<pre>.+)-(?:space|apigateway)\.(?P<rest>.+)$", re.I)


def _derive_service_url(var_name: str, creds: Credentials) -> str:
    """https://<tenant>-<region>-space.<domain>/... -> https://<tenant>-<region>-<service>.<domain>"""
    for candidate in (creds.base_url, creds.apigateway_url, creds.space_url):
        host = httpx.URL(candidate).host if candidate else ""
        m = _SERVICE_HOST.match(host or "")
        if m:
            return f"https://{m.group('pre')}-{var_name.lower()}.{m.group('rest')}"
    return ""


def build_client(spec: dict[str, Any], entry: ServiceEntry, creds: Credentials) -> httpx.AsyncClient:
    preference = entry.server_preference or creds.server_preference
    base_url = _resolve_server_url(spec, preference, creds)

    kwargs = dict(
        base_url=base_url,
        headers=creds.default_headers(),
        timeout=creds.timeout_seconds,
        verify=creds.verify_ssl,
    )
    tenant = resolve_tenant(creds, base_url)
    if tenant:
        logging.getLogger("tdx_mcp.auth").info("Using tenant %s for 3DSpace calls", tenant)
    if creds.use_passport:
        return PassportClient(creds=creds, tenant=tenant, **kwargs)
    return TdxClient(tenant=tenant, **kwargs)


# FastMCP joins paths with urllib's urljoin(), which turns a 3DEXPERIENCE
# path like "dsmfg:MfgItem/search" into a URL whose *scheme* is "dsmfg",
# so httpx drops it and calls ".../dsmfg/MfgItem/search". Put the leading
# slash back for anything that looks like "<word>:<path>" without "//".
_SCHEME_LIKE_PATH = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:(?!//)")


_TENANT_IN_HOST = re.compile(r"^((?:oi|r)\d{6,})-", re.I)


def resolve_tenant(creds: Credentials, base_url: str) -> str:
    """Explicit TDX_TENANT, else the tenant prefix of the 3DSpace host, upper-cased."""
    if creds.tenant:
        return creds.tenant.strip()
    host = httpx.URL(creds.base_url or base_url).host
    m = _TENANT_IN_HOST.match(host or "")
    return m.group(1).upper() if m else ""


class TdxClient(httpx.AsyncClient):
    """AsyncClient that keeps 'dsmfg:' paths intact and adds ?tenant= to 3DSpace calls."""

    def __init__(self, *args: Any, tenant: str = "", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._tenant = tenant
        self._tenant_hosts = {self.base_url.host}

    def build_request(self, method, url, *args, **kwargs):
        if isinstance(url, httpx.URL):
            url = str(url)
        # Request bodies whose schema is a oneOf/anyOf (e.g. dsmfg:MfgItem create)
        # can reach us as a JSON *string* instead of an object, depending on the
        # MCP client. Sent as-is, 3DEXPERIENCE answers "Payload is not valid".
        body = kwargs.get("json")
        if isinstance(body, str) and body.lstrip()[:1] in ("{", "["):
            try:
                kwargs["json"] = json.loads(body)
            except ValueError:
                pass
        content = kwargs.get("content")
        if isinstance(content, (bytes, str)) and content[:1] in (b'"', '"'):
            try:
                outer = json.loads(content)
                if isinstance(outer, str) and outer.lstrip()[:1] in ("{", "["):
                    kwargs["content"] = json.dumps(json.loads(outer)).encode()
                    headers = kwargs.get("headers")
                    if isinstance(headers, list):  # drop the stale Content-Length
                        kwargs["headers"] = [
                            (k, v) for k, v in headers
                            if (k.lower() if isinstance(k, str) else k.decode().lower()) != "content-length"
                        ]
            except ValueError:
                pass
        # Some 3DEXPERIENCE specs declare a JSON array field as "string"
        # (e.g. dscfg:Configured "enabledCriteria"), so the value arrives as
        # '["Variant"]'. Turn top-level string values that are JSON arrays
        # back into arrays; the service rejects them otherwise.
        content = kwargs.get("content")
        if isinstance(content, (bytes, str)) and content[:1] in (b"{", "{"):
            try:
                obj = json.loads(content)
                changed = False
                if isinstance(obj, dict):
                    for key, value in list(obj.items()):
                        if isinstance(value, str) and value.strip()[:1] == "[" and value.strip()[-1:] == "]":
                            try:
                                parsed = json.loads(value)
                            except ValueError:
                                continue
                            if isinstance(parsed, list):
                                obj[key] = parsed
                                changed = True
                if changed:
                    kwargs["content"] = json.dumps(obj).encode()
                    headers = kwargs.get("headers")
                    if isinstance(headers, list):
                        kwargs["headers"] = [
                            (k, v) for k, v in headers
                            if (k.lower() if isinstance(k, str) else k.decode().lower()) != "content-length"
                        ]
            except ValueError:
                pass
        if isinstance(url, str) and _SCHEME_LIKE_PATH.match(url):
            url = "/" + url
        req = super().build_request(method, url, *args, **kwargs)
        if self._tenant and req.url.host in self._tenant_hosts and "tenant" not in req.url.params:
            req.url = req.url.copy_add_param("tenant", self._tenant)
        return req


# ---------------------------------------------------------------------------
# 3DPassport (CAS) session handling
# ---------------------------------------------------------------------------

logger = logging.getLogger("tdx_mcp.auth")

# The login page 3DSpace serves to unauthenticated calls contains e.g.
#   document.location = 'https://<tenant>.iam.3dexperience.3ds.com:443/login?...'
_PASSPORT_IN_PAGE = re.compile(r"""(https://[^'"\s]+?)/login\?""")


class PassportLoginError(RuntimeError):
    pass


_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# The API gateway fronts several backend services (3DSpace, Sourcing, ...).
# We learn which backend serves which gateway path from its login redirects:
#   "/api/dssrc-qualifications" -> "https://<tenant>-sourcing.../enovia"
_GATEWAY_BACKENDS: dict[str, str] = {}


def _gw_prefix(url: httpx.URL) -> str:
    return "/".join(url.path.split("/")[:3])          # "/api/<service>"


def _backend_root(url: httpx.URL) -> str:
    first = url.path.split("/")[1] if url.path.count("/") >= 1 else ""
    return f"{url.scheme}://{url.host}" + (f"/{first}" if first else "")


# Auth trace: one line per HTTP hop, written to <project>/auth_debug.log.
# Records method, URL without query string (so no tickets), status,
# content-type and cookie NAMES only -- never values or passwords.
_TRACE_FILE = Path(__file__).resolve().parent.parent / "auth_debug.log"


def _trace(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    logger.info(line)
    try:
        with open(_TRACE_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def _hop(resp: httpx.Response) -> str:
    req = resp.request
    url = f"{req.url.scheme}://{req.url.host}{req.url.path}"
    sent = sorted({c.split("=", 1)[0].strip() for c in req.headers.get("cookie", "").split(";") if "=" in c})
    got = sorted({h.split("=", 1)[0].strip() for h in resp.headers.get_list("set-cookie")})
    loc = resp.headers.get("location", "")
    if loc:
        loc = " location=" + loc.split("?", 1)[0]
    has_ctx = "yes" if req.headers.get("SecurityContext") else "no"
    if "tenant" in req.url.params:
        url += f" (tenant={req.url.params['tenant']})"
    return (f"{req.method} {url} -> {resp.status_code} "
            f"[{resp.headers.get('content-type', '').split(';')[0]}]{loc} "
            f"sent_cookies={sent} set_cookies={got} SecurityContext={has_ctx}")


def _page_text(resp: httpx.Response) -> str:
    """Title + visible text of a small HTML error page (4xx/5xx only)."""
    if resp.status_code < 400 or "html" not in resp.headers.get("content-type", ""):
        return ""
    try:
        html = resp.text
    except httpx.ResponseNotRead:
        return ""
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    out = (title.group(1).strip() + " | " if title else "") + body[:200]
    return f' page="{out}"'


def _trace_response(label: str, resp: httpx.Response) -> None:
    for i, h in enumerate(list(resp.history) + [resp]):
        _trace(f"{label} #{i}: {_hop(h)}{_page_text(h)}")


# One cookie jar + login per process, shared by every mounted service, so a
# single sign-in covers all specs that talk to the same 3DSpace.
_SHARED_COOKIES = httpx.Cookies()
_LOGIN_LOCK: asyncio.Lock | None = None
_LOGGED_IN_FOR: set[str] = set()


def _login_lock() -> asyncio.Lock:
    global _LOGIN_LOCK
    if _LOGIN_LOCK is None:
        _LOGIN_LOCK = asyncio.Lock()
    return _LOGIN_LOCK


def _looks_like_login(response: httpx.Response) -> bool:
    """True if 3DSpace bounced us to 3DPassport instead of answering."""
    if response.status_code == 401:
        return True
    if response.status_code in (301, 302, 303, 307, 308):
        return "/login" in response.headers.get("location", "")
    ctype = response.headers.get("content-type", "")
    if response.status_code == 200 and "text/html" in ctype:
        try:
            body = response.text
        except httpx.ResponseNotRead:
            return False
        return "/login?" in body and ("iam." in body or "3dpassport" in body.lower())
    return False


def _space_root_for(creds: Credentials, base_url: str) -> str:
    if creds.space_url:
        return creds.space_url.rstrip("/")
    url = httpx.URL(creds.base_url or base_url)
    if "-apigateway." in (url.host or ""):
        return f"https://{url.host.replace('-apigateway.', '-space.', 1)}/enovia"
    return str(creds.base_url or base_url).rstrip("/")


class PassportClient(TdxClient):
    """httpx client that signs in to 3DPassport and keeps the session.

    * logs in lazily before the first call (and after the session expires)
    * re-sends the original call once after a fresh login
    * never exposes the password to the LLM or the logs
    """

    def __init__(self, *, creds: Credentials, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # httpx copies a jar passed to __init__, so share it explicitly.
        self._cookies = _SHARED_COOKIES
        self._creds = creds
        self._passport = creds.passport_url.rstrip("/")
        # 3DSpace root used for login, e.g. https://<tenant>-space.3dexperience.3ds.com/enovia
        self._space_root = _space_root_for(creds, str(self.base_url))
        self._tenant_hosts.add(httpx.URL(self._space_root).host)
        if httpx.URL(self._space_root).host != self.base_url.host:
            logger.info("API calls -> %s ; 3DPassport login via 3DSpace %s", self.base_url, self._space_root)

    # -- public httpx entry point (request()/get()/post() all funnel here) --
    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        if self._space_root not in _LOGGED_IN_FOR:
            await self._login(reason="first call")
            self._apply_cookies(request)
        if request.method in _WRITE_METHODS and self._needs_space_csrf(request):
            await self._attach_csrf(request)

        response = await super().send(request, **kwargs)
        if request.method in _WRITE_METHODS:
            _trace_response(f"write {request.method}", response)
        if not kwargs.get("stream") and _looks_like_login(response):
            _trace_response("API call bounced", response)
            self._discover_passport(response)
            location = response.headers.get("location", "")
            await response.aclose()
            _LOGGED_IN_FOR.discard(self._space_root)
            await self._login(reason="session expired or missing")
            # The API gateway keeps its own 3DSpace session: it redirects to
            # 3DPassport with itself as the service. Now that we hold the
            # 3DPassport cookie, follow that loop so the gateway gets a ticket.
            space_host = httpx.URL(self._space_root).host
            backend = self._backend_from_login_redirect(location)
            if location and request.url.host != space_host:
                if backend and httpx.URL(backend).host not in (space_host, request.url.host):
                    # e.g. qualifications live on the Sourcing service, not 3DSpace
                    _GATEWAY_BACKENDS[_gw_prefix(request.url)] = backend
                    await self._backend_login(backend)
                    self._bridge_space_session(request.url.host, backend)
                    if request.method in _WRITE_METHODS:
                        await self._attach_csrf(request)
                else:
                    await self._complete_cas_redirect(location, request.url)
            self._apply_cookies(request)
            response = await super().send(request, **kwargs)
            if (_looks_like_login(response) and not kwargs.get("stream")
                    and request.url.host != httpx.URL(self._space_root).host
                    and self._bridge_space_session(request.url.host,
                                                   _GATEWAY_BACKENDS.get(_gw_prefix(request.url)))):
                await response.aclose()
                self._apply_cookies(request)
                response = await super().send(request, **kwargs)
                _trace_response("API call after session bridge", response)
            if _looks_like_login(response):
                _trace_response("API call after re-login", response)
                gateway = "-apigateway." in (response.request.url.host or "")
                hint = (
                    "HTTP 401 from the API gateway: the 3DPassport/3DSpace login succeeded, but "
                    "the gateway wants its own credentials (usually an APIKey or bearer token "
                    "for this tenant)."
                    if response.status_code == 401 and gateway else
                    "HTTP 401: the session is valid but 3DSpace refused it -- usually a "
                    "wrong SecurityContext (role.organization.collab space) for this tenant."
                    if response.status_code == 401 else
                    "3DSpace still sends the call to the 3DPassport login page."
                )
                try:
                    said = re.sub(r"\s+", " ", response.text)[:300]
                except httpx.ResponseNotRead:
                    said = ""
                raise PassportLoginError(
                    f"{hint} Details: {_hop(response)}"
                    + (f" Server said: {said}" if said else "")
                    + f". Full trace in {_TRACE_FILE}"
                )
        return response

    # -- helpers ---------------------------------------------------------------
    def _needs_space_csrf(self, request: httpx.Request) -> bool:
        """3DSpace and gateway-relayed writes need ENO_CSRF_TOKEN. Services
        called on their own host (e.g. <tenant>-usersgroup...) do not, and
        must not get 3DSpace session cookies copied to them."""
        host = request.url.host or ""
        return host == httpx.URL(self._space_root).host or "-apigateway." in host

    def _apply_cookies(self, request: httpx.Request) -> None:
        request.headers.pop("Cookie", None)
        self.cookies.set_cookie_header(request)

    def _discover_passport(self, response: httpx.Response) -> None:
        if self._passport:
            return
        text = response.headers.get("location", "")
        if not text:
            try:
                text = response.text
            except httpx.ResponseNotRead:
                text = ""
        m = _PASSPORT_IN_PAGE.search(text)
        if m:
            self._passport = re.sub(r":443$", "", m.group(1).rstrip("/"))
            logger.info("Discovered 3DPassport URL: %s", self._passport)

    async def _complete_cas_redirect(self, location: str, origin: httpx.URL) -> None:
        """Follow 3DPassport -> service?ticket=... so a proxy (the API gateway)
        can create its own 3DSpace session. 3DPassport hops get no API key or
        SecurityContext; hops back to the service get the normal headers."""
        passport_host = httpx.URL(self._passport).host if self._passport else ""
        url = str(origin.join(location))
        for _ in range(6):
            target = httpx.URL(url)
            on_passport = target.host == passport_host or ".iam." in (target.host or "")
            req = self._plain_request("GET", url) if on_passport else self.build_request("GET", url)
            self._apply_cookies(req)
            r = await super().send(req, follow_redirects=False)
            await r.aread()
            _trace_response("gateway ticket hop", r)
            nxt = r.headers.get("location")
            if r.status_code not in (301, 302, 303, 307, 308) or not nxt:
                return
            url = str(target.join(nxt))
            nt = httpx.URL(url)
            # The gateway relays 3DSpace's own login redirect, so 3DPassport
            # issues the ticket for the *3DSpace* URL. Deliver it through the
            # gateway (same path, plus ?ticket=) so 3DSpace validates it inside
            # the gateway's relayed session instead of a separate direct one.
            if "ticket" in nt.params and nt.host not in (origin.host, passport_host):
                via = origin.copy_merge_params({"ticket": nt.params["ticket"]})
                r = await super().send(self.build_request("GET", str(via)), follow_redirects=False)
                await r.aread()
                _trace_response("ticket delivered via gateway", r)
                return
            # Stop once we're sent back to a normal (non-ticket) API URL; the
            # caller re-sends the original request with its own method/body.
            if not (nt.host == passport_host or ".iam." in (nt.host or "")) and "ticket" not in nt.params:
                return

    async def _attach_csrf(self, request: httpx.Request) -> None:
        """3DSpace write calls need ENO_CSRF_TOKEN from the *same* session.
        Fetch it from 3DSpace and, for gateway calls, make the gateway relay
        that same session. Overrides any value the caller (LLM) supplied."""
        space_host = httpx.URL(self._space_root).host
        root = self._space_root
        if request.url.host != space_host:
            root = _GATEWAY_BACKENDS.get(_gw_prefix(request.url), self._space_root)
        r = await super().send(
            self._plain_request("GET", f"{root}/resources/v1/application/CSRF"),
            follow_redirects=False,
        )
        await r.aread()
        name, value = "ENO_CSRF_TOKEN", ""
        try:
            csrf = r.json().get("csrf") or {}
            name, value = csrf.get("name") or name, csrf.get("value") or ""
        except ValueError:
            pass
        _trace(f"csrf fetch: {_hop(r)} token={'yes' if value else 'NO'}")
        if not value:
            raise PassportLoginError(
                f"Could not get a CSRF token from {root} (HTTP {r.status_code}); write calls need one."
            )
        if request.url.host != httpx.URL(root).host:
            self._bridge_space_session(request.url.host, root)
            self._apply_cookies(request)
        request.headers[name] = value

    def _cookie_prefix(self, backend_host: str, gateway_host: str) -> str:
        """Gateway cookie prefix for a backend: 3DSPACE_ for 3DSpace,
        Sourcing_ for <tenant>-sourcing..., matched against cookies the
        gateway has already set, else derived from the host name."""
        label = (backend_host or "").split(".")[0].rsplit("-", 1)[-1].lower()
        norm = lambda x: x.lower().replace("3d", "")
        for c in self.cookies.jar:
            if c.domain.lstrip(".") == gateway_host and c.name.endswith("_JSESSIONID"):
                pre = c.name[: -len("_JSESSIONID")]
                if norm(pre) == norm(label):
                    return pre
        return "3DSPACE" if label == "space" else label.capitalize()

    def _bridge_space_session(self, gateway_host: str, backend_root: str | None = None) -> bool:
        """The API gateway stores each relayed backend's cookies as
        <PREFIX>_<name> (3DSPACE_JSESSIONID, Sourcing_JSESSIONID, ...).
        Copy our signed-in backend session there."""
        backend_host = httpx.URL(backend_root or self._space_root).host
        prefix = self._cookie_prefix(backend_host, gateway_host)
        for c in list(self.cookies.jar):
            if c.domain.lstrip(".") == gateway_host and c.name.startswith(prefix + "_"):
                self.cookies.jar.clear(c.domain, c.path, c.name)
        copied = []
        for c in list(self.cookies.jar):
            if c.domain.lstrip(".") == backend_host and c.name in ("JSESSIONID", "SERVERID"):
                self.cookies.set(f"{prefix}_{c.name}", c.value, domain=gateway_host, path="/")
                copied.append(c.name)
        _trace(f"session bridge {backend_host} -> {gateway_host}: copied {copied or 'nothing'} as {prefix}_*")
        return bool(copied)

    def _backend_from_login_redirect(self, location: str) -> str | None:
        """From '<passport>/login?service=<backend URL>' return the backend root."""
        if not location:
            return None
        try:
            svc = httpx.URL(location).params.get("service")
            return _backend_root(httpx.URL(svc)) if svc else None
        except Exception:
            return None

    async def _backend_login(self, backend_root: str) -> bool:
        """Silent 3DPassport sign-in to another backend (e.g. Sourcing), using
        the CASTGC cookie from the main login: no password is sent again.
        Uses the backend's CSRF endpoint, which accepts GET."""
        self._tenant_hosts.add(httpx.URL(backend_root).host)
        t = f"?tenant={self._tenant}" if self._tenant else ""
        service = f"{backend_root}/resources/v1/application/CSRF{t}"
        r = await super().send(
            self._plain_request("GET", f"{self._passport}/login", params={"service": service}),
            follow_redirects=True,
        )
        await r.aread()
        label = backend_root.split("//", 1)[-1].split(".")[0]
        _trace_response(f"backend login {label}", r)
        chk = await super().send(
            self._plain_request("GET", f"{backend_root}/resources/v1/application/CSRF"),
            follow_redirects=False,
        )
        await chk.aread()
        ok = chk.status_code == 200 and "json" in chk.headers.get("content-type", "")
        _trace(f"backend session check {label}: {'OK' if ok else 'NOT signed in'} -- {_hop(chk)}")
        return ok

    def _plain_request(self, method: str, url: str, **kwargs: Any) -> httpx.Request:
        """Request for login traffic: no SecurityContext/Authorization/APIKey."""
        req = self.build_request(method, url, **kwargs)
        for h in ("SecurityContext", "Authorization", "APIKey"):
            req.headers.pop(h, None)
        return req

    async def _probe_passport(self) -> None:
        """Hit 3DSpace once without a session to learn the 3DPassport URL."""
        probe = self._plain_request("GET", f"{self._space_root}/resources/v1/application/CSRF")
        resp = await super().send(probe, follow_redirects=False)
        await resp.aread()
        _trace_response("probe", resp)
        self._discover_passport(resp)
        if not self._passport:
            raise PassportLoginError(
                "Could not determine the 3DPassport URL; set TDX_PASSPORT_URL in .env "
                "(e.g. https://<tenant>.iam.3dexperience.3ds.com)."
            )

    async def _login(self, reason: str) -> None:
        async with _login_lock():
            if self._space_root in _LOGGED_IN_FOR:
                return  # another task logged in while we waited
            # A still-valid 3DSpace session (shared cookie jar) needs no new login.
            if self._cookies.jar and await self._session_ok("existing session"):
                _LOGGED_IN_FOR.add(self._space_root)
                return
            if not self._passport:
                await self._probe_passport()

            logger.info("Signing in to 3DPassport as %s (%s)", self._creds.username, reason)
            # 1) login ticket
            r = await super().send(
                self._plain_request(
                    "GET", f"{self._passport}/login",
                    params={"action": "get_auth_params"},
                    headers={"Accept": "application/json"},
                ),
                follow_redirects=True,
            )
            _trace_response("login ticket", r)
            try:
                lt = r.json().get("lt")
            except ValueError:
                lt = None
            if not lt:
                raise PassportLoginError(
                    f"3DPassport did not return a login ticket (HTTP {r.status_code}). "
                    "If your tenant uses SSO, username/password login is not available."
                )

            # 2) credentials -> service ticket -> 3DSpace session cookies.
            #    3DSpace tenants differ in which "service" URL they accept for
            #    the ticket hand-off, so try the usual candidates in turn. After
            #    the first password submit, 3DPassport's CASTGC cookie lets us
            #    get further tickets without sending the password again.
            t = f"?tenant={self._tenant}" if self._tenant else ""
            candidates = [
                f"{self._space_root}/{t}",
                f"{self._space_root}/resources/v1/application/CSRF{t}",
                f"{self._space_root}/common/emxNavigator.jsp{t}",
                f"{self._space_root}/",
            ]
            for n, service in enumerate(candidates):
                if n == 0:
                    r = await super().send(
                        self._plain_request(
                            "POST", f"{self._passport}/login",
                            params={"service": service},
                            data={
                                "lt": lt,
                                "username": self._creds.username,
                                "password": self._creds.password,
                                "rememberMe": "no",
                            },
                        ),
                        follow_redirects=True,
                    )
                else:
                    r = await super().send(
                        self._plain_request("GET", f"{self._passport}/login", params={"service": service}),
                        follow_redirects=True,
                    )
                label = service.replace(self._space_root, "<3DSpace>")
                _trace_response(f"login via service={label}", r)
                if n == 0 and str(r.url).startswith(self._passport):
                    detail = ""
                    try:
                        j = r.json()
                        detail = j.get("errorMsg") or j.get("error") or j.get("message") or ""
                    except ValueError:
                        pass
                    raise PassportLoginError(
                        "3DPassport rejected the login"
                        + (f": {detail}" if detail else " (check TDX_USERNAME / TDX_PASSWORD)")
                    )
                if await self._session_ok(label):
                    _LOGGED_IN_FOR.add(self._space_root)
                    logger.info("3DPassport login OK (service=%s)", label)
                    return

            _trace("cookie jar holds: " + ", ".join(sorted(f"{c.name}@{c.domain}{c.path}" for c in self.cookies.jar)))
            raise PassportLoginError(
                "3DPassport accepted the password, but 3DSpace refused every ticket hand-off "
                "(HTTP 403). The account is probably not granted access to this tenant's "
                f"3DSpace. Details in {_TRACE_FILE}"
            )

    async def _session_ok(self, label: str) -> bool:
        """Is there a usable 3DSpace session? (CSRF needs no SecurityContext.)"""
        try:
            chk = await super().send(
                self._plain_request("GET", f"{self._space_root}/resources/v1/application/CSRF"),
                follow_redirects=False,
            )
            await chk.aread()
        except httpx.HTTPError as e:
            _trace(f"session check after service={label} failed: {type(e).__name__}")
            return False
        ok = chk.status_code == 200 and "json" in chk.headers.get("content-type", "")
        _trace(f"session check after service={label}: {'OK' if ok else 'NOT signed in'} -- {_hop(chk)}")
        return ok
