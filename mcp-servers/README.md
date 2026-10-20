# MCP servers for 3DEXPERIENCE and Catia Magic

Arun's MCP servers and supporting tools, one folder each. Every folder has its
own README with setup steps.

| Folder | What it is | Runs where |
|---|---|---|
| [`tdx-mcp-server`](tdx-mcp-server) | 3DEXPERIENCE REST APIs (Manufacturing, Engineering, MEI, Qualification, Documents, Routes, User Groups, Portfolio) exposed as MCP tools via FastMCP + OpenAPI | Locally (stdio) **or** remotely on Cloud Run — see [`DEPLOY-CLOUDRUN.md`](tdx-mcp-server/DEPLOY-CLOUDRUN.md) |
| [`magic-mcp-server`](magic-mcp-server) | Catia Magic Systems of Systems Architect: Python MCP server + Java plugin bridge | Locally only (needs Catia Magic on the same PC) |
| [`float-on-release`](float-on-release) | Replaces a released Manufacturing Item in its parents' MBOMs; triggered by EIF "Status Change → Released" events | Locally |
| [`configured-mbom-builder`](configured-mbom-builder) | Builds configured MBOMs from an Excel template | Locally |
| [`eif-listener`](eif-listener) | .NET listener that receives 3DEXPERIENCE EIF events and writes them to disk for Float on Release | Locally |

## Secrets

Nothing secret is committed. Each server reads credentials from its own `.env`
(copy `.env.example`); the EIF listener reads `agent.secret`. Both are ignored
by `.gitignore`. Run outputs (`runs/`, `events/`, `logs/`) stay local too.

## Setup after cloning

```powershell
cd <folder>
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env   # then fill it in
```

Folders with an `install.ps1` can be set up with that script instead.
