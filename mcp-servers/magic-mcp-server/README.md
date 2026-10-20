# Catia Magic MCP Server (FastMCP)

Lets Claude read and edit the model open in **Catia Magic Systems of Systems
Architect** (SysML + UAF) on this computer. Same
stack as the 3DEXPERIENCE MCP server: Python, FastMCP, `.env`, stdio for the Claude desktop app.

## How it works

```
Claude desktop app ──stdio──> server.py (FastMCP, this folder)
                                   │  HTTP POST /api/<action>
                                   │  127.0.0.1:8765 + secret token
                                   ▼
                    Magic MCP Bridge plugin (Java, runs inside Catia Magic)
                                   │  Catia Magic OpenAPI, on the Swing thread
                                   ▼
                          the project open in Catia Magic
```

```
magic-mcp-server/
├── server.py              # entrypoint (stdio or streamable-http)
├── app/
│   ├── config.py          # .env settings (read-only mode, timeouts)
│   ├── bridge.py          # HTTP client for the plugin
│   └── tools.py           # the 15 MCP tools
├── plugin/
│   ├── src/com/arun/magicbridge/   # Java plugin source
│   ├── plugin.xml         # Catia Magic plugin descriptor
│   └── build.ps1          # build + install into Catia Magic
├── install.ps1          # sets up .venv and .env, prints the Claude Desktop entry
├── .env.example
└── requirements.txt
```

Unlike the 3DEXPERIENCE MCP server, the tools are hand-written rather than generated from
an OpenAPI spec: 15 well-described tools work better for an LLM than hundreds
of generic ones, and Catia Magic has no REST spec for the desktop app anyway.

## Tools

| Read | Edit |
|---|---|
| `get_project` – project, root model, top-level packages, profiles | `create_element` – Block, Requirement, Package, any UML metaclass, + any stereotype (UAF too) and tagged values |
| `search_elements` – by name / type / stereotype | `add_property` – part, reference, value property or proxy port on a block |
| `get_element` – details, tagged values, parts, children, relationships | `update_element` – rename, document, retype, move, set tags |
| `list_children` – containment tree | `apply_stereotype` – apply or remove |
| `get_relationships` | `create_relationship` – Satisfy, DeriveReqt, Refine, Trace, Verify, Allocate, Generalization, Dependency (+ UAF stereotype) … |
| `list_diagrams`, `open_diagram` | `delete_element` |
| `list_stereotypes` – find UAF/SysML stereotypes and their metaclasses | `save_project` – local .mdzip only |

Every edit is a single undoable step in Catia Magic (**Edit › Undo "MCP: …"**),
and a failed edit is rolled back completely. Elements in used projects, or not
locked on a server project, are refused as read-only.

## Get it from GitLab

Project: <https://itgit.dsone.3ds.com/HJH/magic-mcp-server> (private; ask the owner to add you
as a member with the **Reporter** role).

**Option A: Clone** (recommended; updates are then one command)

```powershell
cd C:\MCP
git clone https://itgit.dsone.3ds.com/HJH/magic-mcp-server.git
```

If Git asks for a password, use a GitLab **personal access token** (scope `read_repository`), not your
normal password.

**Option B: Download**: on the project page, **Code → Download source code → zip**, and unzip it to
`C:\MCP\magic-mcp-server`.

Then follow **Setup** below.

### Updates

If you cloned: `cd C:\MCP\magic-mcp-server`, then `git pull`, then restart Claude Desktop.
If `plugin/src` changed, also rebuild the plugin (step 1 of Setup) and restart Catia Magic.
Your `.env` and `.venv` are not touched (Git ignores them).

## Setup (Windows)

Requirements: Catia Magic Systems of Systems Architect (2022x–2026x), a JDK 11+ to build the plugin,
Python 3.10+, and the Claude desktop app.

### 1. Build and install the plugin

Needs a JDK 11+ (`javac`). Close Catia Magic, open PowerShell **as Administrator**
(Catia Magic is usually under Program Files), then:

```powershell
cd C:\MCP\magic-mcp-server\plugin
.\build.ps1 -Install
# or, if it can't find your install:
.\build.ps1 -MagicHome "C:\Program Files\Catia Magic Systems of Systems Architect 2024x" -Install
```

Start Catia Magic. **Help › About › Plugins** should list *Magic MCP Bridge*,
and `%USERPROFILE%\.magic-mcp\bridge.json` should appear.

### 2. Python server

Needs Python 3.10+. In the project folder:

```powershell
cd C:\MCP\magic-mcp-server
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

This creates `.venv`, installs the packages, creates `.env` (optional settings) and prints the
exact Claude Desktop entry for your folder.

### 3. Register in the Claude desktop app

Paste the entry `install.ps1` printed into `%APPDATA%\Claude\claude_desktop_config.json`
under `"mcpServers"`. It looks like this (with your own folder):

```json
"catia-magic": {
  "command": "C:\\MCP\\magic-mcp-server\\.venv\\Scripts\\python.exe",
  "args": ["C:\\MCP\\magic-mcp-server\\server.py"]
}
```

Quit the Claude desktop app completely (also from the system tray) and start it again. With a project open in Catia Magic, ask e.g.
*"List the UAF capabilities in my model"* or *"Create a Satisfy from Radar to R-12"*.

## Settings (`.env`)

| Variable | Default | |
|---|---|---|
| `MAGIC_READ_ONLY` | `false` | `true` registers only the read tools |
| `MAGIC_ALLOW_DELETE` | `true` | `false` hides `delete_element` |
| `MAGIC_TIMEOUT_SECONDS` | `60` | how long to wait for Catia Magic |
| `MAGIC_BRIDGE_PORT` | from bridge.json | only if you changed the plugin's port |
| `MAGIC_BRIDGE_TOKEN_FILE` | `~/.magic-mcp/bridge.json` | |

To move the plugin off port 8765, add `-Dmagicbridge.port=NNNN` to the Catia
Magic `.vmoptions` / launcher properties (or set `MAGIC_BRIDGE_PORT` in its environment).

## Security

- The bridge listens on `127.0.0.1` only.
- Every call needs a random 256-bit token that the plugin regenerates at each
  start and writes to `bridge.json` in your user profile; the Python server
  reads it on every call, so restarting Catia Magic needs nothing else.
- Requests from web pages (any `Origin` header) are rejected.
- There is no "run arbitrary script" endpoint.

## Troubleshooting

- **"Can't reach Catia Magic"** – Catia Magic isn't open, or the plugin didn't
  load: check `bridge.json` exists and look for `[MagicMCPBridge]` in the
  Catia Magic log (`Help › Open Log File`).
- **Compile errors in `build.ps1`** – the code targets the 2022x–2026x OpenAPI.
  Paste the error to Claude with your Catia Magic version.
- **Timeouts** – a modal dialog in Catia Magic blocks the UI thread; close it.
- **Server projects** (Teamwork Cloud / 3DEXPERIENCE) – lock the elements
  before editing, and commit from Catia Magic; `save_project` only saves local files.

## Testing done

Built against stubs of the Catia Magic OpenAPI (signatures checked against the
2026x javadoc) and run end to end through the real MCP tools against an
in-memory fake model: reads, every edit tool, tagged values, read-only refusal,
rollback on error, token/Origin rejection, and read-only mode.

Also tested by the author inside a real Catia Magic Systems of Systems Architect install on Windows,
through the Claude desktop app.
