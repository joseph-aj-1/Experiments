"""Entrypoint for the 3DEXPERIENCE MCP server.

Run:
    python server.py                  # stdio transport (Claude Desktop, Claude Code)
    python server.py --http           # streamable-http on 0.0.0.0:8000 (local test)

Remote / Cloud Run:
    Set TDX_AUTH=github (+ the variables listed in app/remote_auth.py) and run
    `python server.py --http`. The port comes from $PORT when Cloud Run sets it.
    The MCP endpoint is <public-url>/mcp
"""
from __future__ import annotations

import argparse
import logging
import os

from app.loader import build_app
from app.remote_auth import build_auth

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

if __name__ != "__main__":
    # Keeps `from server import mcp` working for anything that imports it.
    mcp = build_app()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true", help="Serve over streamable-http instead of stdio")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    args = parser.parse_args()

    if args.http:
        auth = build_auth()
        if auth is None and args.host not in ("127.0.0.1", "localhost"):
            logging.warning(
                "HTTP mode WITHOUT authentication on %s. Anyone who can reach this port can use "
                "your 3DEXPERIENCE login. Set TDX_AUTH=github before exposing it publicly.",
                args.host,
            )
        mcp = build_app(auth=auth)
        from starlette.middleware import Middleware

        from app.http_sanitizer import SanitizerMiddleware

        # Stateless so any Cloud Run instance / cold start can serve any request.
        # json_response + SanitizerMiddleware give remote clients the same
        # API-safe tool schemas that mcp_schema_sanitizer.py gives Claude Desktop.
        mcp.run(
            transport="streamable-http",
            host=args.host,
            port=args.port,
            stateless_http=True,
            json_response=True,
            middleware=[Middleware(SanitizerMiddleware, mcp=mcp, path="/mcp")],
        )
    else:
        mcp = build_app()
        mcp.run()
