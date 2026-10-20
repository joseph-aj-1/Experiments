"""Entrypoint for the Catia Magic MCP server.

Run:
    python server.py                  # stdio transport (Claude Desktop, etc.)
    python server.py --http           # streamable-http on 127.0.0.1:8001
"""
from __future__ import annotations

import argparse
import logging

from fastmcp import FastMCP

from app.tools import register

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

mcp = FastMCP(
    "Catia Magic MCP Server",
    instructions=(
        "Tools for the model open in Catia Magic Systems of Systems Architect (SysML + UAF). "
        "Start with get_project, then search_elements / get_element to find things by ID. "
        "Use list_stereotypes to find UAF stereotypes before creating UAF elements. "
        "Each edit is one undoable step in Catia Magic. Ask the user before deleting anything."
    ),
)
register(mcp)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true", help="Serve over streamable-http instead of stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    if args.http:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)
    else:
        mcp.run()
