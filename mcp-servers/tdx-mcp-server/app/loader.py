"""Turns config/services.yaml + specs/*.json into a composed FastMCP app.

This is the dynamic-registration engine: add a webservice by dropping a
spec file and a services.yaml entry; remove one by disabling/deleting the
entry. No other code changes are required.
"""
from __future__ import annotations

import json
import logging

import yaml
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap
from fastmcp.utilities.openapi import HTTPRoute

from app.client_factory import build_client
from app.config import CREDENTIALS, ServiceEntry, load_services

logger = logging.getLogger("tdx_mcp")

# Headers that are supplied automatically by the httpx client (see
# app/client_factory.py) and must never be surfaced as LLM-fillable tool
# arguments, even though the 3DEXPERIENCE specs declare them as required
# per-operation header parameters.
INJECTED_HEADERS = {"Authorization", "SecurityContext", "APIKey"}


# In HTTP mode FastMCP copies the caller's inbound HTTP headers onto every
# outgoing 3DEXPERIENCE request (it already drops Authorization/Cookie).
# Behind Cloud Run / Claude's cloud those are proxy, tracing and MCP
# headers that 3DX has no use for, so only these are allowed through.
_ALLOWED_OUTBOUND = {
    "accept", "accept-encoding", "accept-language", "content-type", "content-length",
    "host", "cookie", "user-agent", "authorization", "securitycontext", "apikey",
    "enovia_csrf", "x-requested-with", "origin", "referer",
}


async def _drop_forwarded_headers(request) -> None:
    for name in list(request.headers.keys()):
        lower = name.lower()
        if lower in _ALLOWED_OUTBOUND or lower.endswith("csrf") or lower.endswith("csrftoken"):
            continue
        if lower.startswith(("x-forwarded", "x-cloud-trace", "traceparent", "tracestate",
                             "forwarded", "via", "mcp-", "x-envoy", "x-goog", "x-anthropic",
                             "baggage", "sec-", "priority")):
            del request.headers[name]


def _load_spec(path) -> dict:
    with open(path) as f:
        if path.suffix in (".yaml", ".yml"):
            return yaml.safe_load(f)
        return json.load(f)


def _strip_injected_headers(route: HTTPRoute, component) -> None:
    """mcp_component_fn: remove auth headers from the tool's input schema."""
    params = getattr(component, "parameters", None)
    if not isinstance(params, dict):
        return
    props = params.get("properties", {})
    required = params.get("required", [])
    for header_name in INJECTED_HEADERS:
        props.pop(header_name, None)
        if header_name in required:
            required.remove(header_name)


def _make_route_map_fn(entry: ServiceEntry):
    exclude_paths = set(entry.exclude_paths)
    exclude_op_ids = set(entry.exclude_operation_ids)
    exclude_tags = set(entry.exclude_tags)

    def route_map_fn(route: HTTPRoute, mcp_type: MCPType):
        if route.path in exclude_paths:
            return MCPType.EXCLUDE
        if route.operation_id in exclude_op_ids:
            return MCPType.EXCLUDE
        if exclude_tags and exclude_tags.intersection(route.tags or []):
            return MCPType.EXCLUDE
        return None  # defer to default route maps

    return route_map_fn


def build_service_server(entry: ServiceEntry) -> FastMCP | None:
    if not entry.spec_path.exists():
        logger.warning("Skipping '%s': spec file not found at %s", entry.name, entry.spec_path)
        return None

    spec = _load_spec(entry.spec_path)
    client = build_client(spec, entry, CREDENTIALS)
    client.event_hooks.setdefault("request", []).append(_drop_forwarded_headers)

    if entry.tool_names:
        known = {
            op.get("operationId")
            for item in spec.get("paths", {}).values()
            for op in item.values()
            if isinstance(op, dict)
        }
        for op_id in entry.tool_names:
            if op_id not in known:
                logger.warning("'%s': tool_names entry '%s' matches no operationId in %s",
                               entry.name, op_id, entry.file)

    sub_server = FastMCP.from_openapi(
        openapi_spec=spec,
        client=client,
        name=spec.get("info", {}).get("title", entry.name),
        route_maps=[RouteMap(mcp_type=MCPType.TOOL)],  # every remaining op -> tool
        route_map_fn=_make_route_map_fn(entry),
        mcp_component_fn=_strip_injected_headers,
        mcp_names=entry.tool_names or None,
        tags={entry.name},
    )
    return sub_server


def build_app(app_name: str = "3DEXPERIENCE MCP Server", auth=None) -> FastMCP:
    main = FastMCP(app_name, auth=auth)

    entries = load_services()
    if not entries:
        logger.warning(
            "No services configured in config/services.yaml -- server will expose no tools."
        )

    for entry in entries:
        if not entry.enabled:
            logger.info("Service '%s' disabled, skipping.", entry.name)
            continue

        sub_server = build_service_server(entry)
        if sub_server is None:
            continue

        namespace = entry.prefix or entry.name
        main.mount(sub_server, namespace=namespace)
        logger.info("Mounted service '%s' under namespace '%s'", entry.name, namespace)

    return main
