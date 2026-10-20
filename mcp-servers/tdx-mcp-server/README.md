# 3DEXPERIENCE MCP Server (FastMCP)

Exposes 3DEXPERIENCE platform REST webservices (3DSpace/ENOVIA OpenAPI specs)
as MCP tools, built on [FastMCP](https://gofastmcp.com)'s `from_openapi()`
auto-conversion. New webservices are added or removed by editing a config
file — no Python code changes required.

## How it works

```
tdx-mcp-server/
├── .env                    # your real credentials (copy from .env.example)
├── .env.example
├── config/
│   └── services.yaml       # <-- the dynamic on/off switch
├── specs/
│   └── Manufacturing.json  # OpenAPI spec(s), drop new ones here
├── app/
│   ├── config.py           # loads .env + services.yaml
│   ├── client_factory.py   # resolves {3DSpace}/{APIGateway} -> real host,
│   │                       # builds an authenticated httpx.AsyncClient
│   └── loader.py           # for each enabled entry: spec -> FastMCP.from_openapi()
│                            # -> mounted onto the main server under a namespace
└── server.py                # entrypoint (stdio or streamable-http)
```

For each entry in `config/services.yaml`, `loader.py`:
1. Loads the OpenAPI spec from `specs/`
2. Resolves its `servers[]` template (`{3DSpace}` / `{APIGateway}`) against
   `TDX_BASE_URL` / `TDX_APIGATEWAY_URL` in `.env`
3. Builds an `httpx.AsyncClient` with `Authorization` / `SecurityContext` /
   `APIKey` set as default headers
4. Calls `FastMCP.from_openapi(...)` to turn every operation into a tool
5. Mounts that sub-server onto the main app under a namespace prefix
   (e.g. `mfg_search_...`) so multiple specs never collide

## Adding a webservice

1. Drop the OpenAPI JSON/YAML spec into `specs/`
2. Add an entry to `config/services.yaml`:
   ```yaml
   - name: change_action
     file: ChangeAction.json
     enabled: true
     prefix: chg
   ```
3. Restart the server

## Removing / disabling a webservice

Set `enabled: false` on its entry (keeps the file for later), or delete the
entry and the spec file entirely.

## Trimming what a single spec exposes

3DEXPERIENCE specs often bundle dozens of operations per corpus. Use these
per-entry fields to hide the ones you don't want an LLM calling, without
touching the spec file:

```yaml
- name: manufacturing
  file: Manufacturing.json
  prefix: mfg
  exclude_tags: ["internal"]
  exclude_operation_ids: ["DELETE_dsmfg:MfgItem_ID"]
  exclude_paths: ["/dsmfg:MfgItem/{ID}"]
```

## Authentication

3DEXPERIENCE specs typically declare `SecurityContext` as a **required
header parameter on every single operation**, and use `BasicAuth` /
gateway API keys for `Authorization` / `APIKey`. If left alone, FastMCP
would ask the LLM to supply these on every tool call — which is both
noisy and a credential leak risk.

Instead:
- `client_factory.py` sets `Authorization`, `SecurityContext`, and `APIKey`
  as **default headers** on the `httpx.AsyncClient` (from `.env`, never
  from the LLM).
- `loader.py` passes an `mcp_component_fn` that strips those three keys out
  of every generated tool's input schema, so they never appear as
  arguments the LLM has to fill in — this was verified empirically:
  removing a header from `OpenAPITool.parameters` does **not** cause a
  "missing required parameter" error at call time; the client's default
  header is what actually gets sent.

If you need per-call SecurityContext switching (e.g. multiple roles or
collaborative spaces in one session), remove `SecurityContext` from
`INJECTED_HEADERS` in `app/loader.py` so it stays an exposed tool
argument, and drop it from `Credentials.default_headers()`.

> **Note if you later expose this over `streamable-http` to remote MCP
> clients:** FastMCP forwards certain incoming transport headers to the
> downstream API by default, which can override your configured
> `Authorization` header. Pin your `fastmcp` version and check
> [gofastmcp.com](https://gofastmcp.com) / the FastMCP changelog for the
> current behavior before deploying over HTTP with real credentials.

## Running

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in real Authorization / SecurityContext / APIKey / TDX_BASE_URL
python server.py                 # stdio, for Claude Desktop / Claude Code
python server.py --http --port 8000   # streamable-http
```

### Wiring into Claude Desktop / Claude Code

```json
{
  "mcpServers": {
    "3dx": {
      "command": "python",
      "args": ["/absolute/path/to/tdx-mcp-server/server.py"]
    }
  }
}
```

## Notes on the Manufacturing.json spec included here

This repo ships with the `dsmfg` (Manufacturing Item) corpus you uploaded:
69 paths / 99 operations covering search, CRUD on Manufacturing Items and
Instances, engineering-item scoping, alternates/substitutes, and change
control impact. It mounts under the `mfg` prefix (e.g.
`mfg_GETSearch_dsmfgMfgItem_Search`).

## Caveats / things worth tightening before production use

- **Tool count**: FastMCP's own docs note that LLMs perform noticeably
  better with curated tool sets than fully auto-converted ones — with 99
  operations in this one spec alone, consider using `exclude_tags` /
  `exclude_operation_ids` to only expose what your use case actually
  needs, per service.
- **SSL verification**: `TDX_VERIFY_SSL=false` is available for internal
  self-signed 3DSpace instances but should stay `true` in production.
- **Secrets**: `.env` is never committed; `.env.example` documents the
  shape only.
