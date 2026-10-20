"""Schema sanitizing for HTTP (remote) mode.

Locally, Claude Desktop runs this server behind mcp_schema_sanitizer.py, a
stdio proxy that rewrites tool schemas the Anthropic API would reject
(property names like "dsmfg:MfgItem" or "$mask", $refs, top-level anyOf ...).
A remote connector has no such proxy, so without this middleware most tools
(including all the search/GET ones) are dropped by claude.ai.

This ASGI middleware applies the same rewriting to the HTTP endpoint, reusing
the proxy's own ToolTable / restore_args so both paths behave identically:

  tools/list response -> tool names and inputSchemas sanitized
  tools/call request  -> sanitized tool and argument names mapped back

The server runs with json_response=True so responses are plain JSON bodies.
"""
from __future__ import annotations

import asyncio
import json
import logging

from mcp_schema_sanitizer import ToolTable, restore_args

logger = logging.getLogger("tdx_mcp.sanitizer")


class SanitizerMiddleware:
    def __init__(self, app, mcp=None, path: str = "/mcp"):
        self.app = app
        self.mcp = mcp
        self.path = path.rstrip("/")
        self.table = ToolTable()
        self._primed = False
        self._prime_lock = asyncio.Lock()

    async def _prime(self) -> None:
        """Build the name/argument maps without waiting for a tools/list.

        Needed because Cloud Run instances are stateless: after a cold start,
        Claude may call a tool (by its sanitized name) before listing tools.
        """
        if self._primed or self.mcp is None:
            return
        async with self._prime_lock:
            if self._primed:
                return
            tools = await self.mcp.list_tools(run_middleware=False)
            dicts = [
                t.to_mcp_tool().model_dump(by_alias=True, exclude_none=True, mode="json")
                for t in tools
            ]
            _, report = self.table.sanitize_tools(dicts)
            self._primed = True
            logger.info("Sanitizer primed: %d tools, %d adjusted", len(dicts), len(report))

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path", "").rstrip("/") != self.path
        ):
            await self.app(scope, receive, send)
            return

        # --- read and rewrite the request body -------------------------------
        chunks = []
        more = True
        while more:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                return
            chunks.append(msg.get("body", b""))
            more = msg.get("more_body", False)
        body = b"".join(chunks)

        list_ids: set[str] = set()
        try:
            payload = json.loads(body) if body else None
        except ValueError:
            payload = None

        if payload is not None:
            messages = payload if isinstance(payload, list) else [payload]
            changed = False
            for m in messages:
                if not isinstance(m, dict):
                    continue
                method = m.get("method")
                if method == "tools/list" and "id" in m:
                    list_ids.add(json.dumps(m["id"]))
                elif method == "tools/call":
                    await self._prime()
                    params = m.get("params") or {}
                    orig, rmap = self.table.lookup(params.get("name"))
                    if orig != params.get("name"):
                        params["name"] = orig
                        changed = True
                    if rmap is not None:
                        params["arguments"] = restore_args(params.get("arguments"), rmap)
                        changed = True
                    m["params"] = params
            if changed:
                body = json.dumps(payload).encode("utf-8")

        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        if not list_ids:
            await self._call_with_fixed_length(scope, replay, send, body)
            return

        # --- buffer and rewrite a tools/list response -------------------------
        start = None
        resp_chunks = []

        async def capture(message):
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
            elif message["type"] == "http.response.body":
                resp_chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    await self._send_rewritten(start, b"".join(resp_chunks), list_ids, send)
            else:
                await send(message)

        await self._call_with_fixed_length(scope, replay, capture, body)

    async def _call_with_fixed_length(self, scope, receive, send, body):
        headers = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"content-length"]
        headers.append((b"content-length", str(len(body)).encode()))
        await self.app(dict(scope, headers=headers), receive, send)

    async def _send_rewritten(self, start, raw, list_ids, send):
        ctype = dict((k.lower(), v) for k, v in (start or {}).get("headers", [])).get(
            b"content-type", b""
        )
        out = raw
        if b"json" in ctype:
            try:
                payload = json.loads(raw)
                messages = payload if isinstance(payload, list) else [payload]
                for m in messages:
                    if (
                        isinstance(m, dict)
                        and json.dumps(m.get("id")) in list_ids
                        and isinstance(m.get("result"), dict)
                        and isinstance(m["result"].get("tools"), list)
                    ):
                        m["result"]["tools"], report = self.table.sanitize_tools(m["result"]["tools"])
                        self._primed = True
                        logger.info("tools/list sanitized: %d tools, %d adjusted",
                                    len(m["result"]["tools"]), len(report))
                out = json.dumps(payload).encode("utf-8")
            except ValueError:
                out = raw
        headers = [(k, v) for k, v in start.get("headers", []) if k.lower() != b"content-length"]
        headers.append((b"content-length", str(len(out)).encode()))
        await send(dict(start, headers=headers))
        await send({"type": "http.response.body", "body": out, "more_body": False})
