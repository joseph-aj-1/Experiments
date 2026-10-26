# MBOM Copier: 3DEXPERIENCE 3DDashboard widget

Drop a Manufacturing Item in this widget and you see its whole MBOM. You can then copy that MBOM to another tenant (for example Lighthouse) with **Dry run → Copy**.

- **Preview.** As soon as you drop or search an item, the widget reads the structure with your own dashboard sign-in. It shows the levels, the instances, the quantities of continuous materials, and the items that are used more than once.
- **Dry run.** The widget sends the structure to the **MBOM Copier service on your PC**. The service checks the target and shows, per row, what it would *Create* or *Reuse*. Nothing is written.
- **Copy.** You click twice to confirm. The service then creates the items and instances in the target, shows its progress, and finishes by reading the target back and comparing it with the source. If a copy stops partway, press Copy again and it finishes; nothing is created twice.

- **Also copy** associated objects of the copied items. Tick any of:
  - **Change Actions:** a new CA per source CA (title, description, severity), with the copied items as proposed changes (current version, Modify). State, approvals and realized changes start fresh.
  - **Plants:** Manufacturing Responsibility links, with plants matched by name in the target and the same Make/Buy. A plant missing in the target is reported and skipped. *Plant lookup is waiting for the organizations API spec.*
  - **MEIs:** reused if the target has the same manufacturer and part number, otherwise created, then qualified on the copied part with the same preferred and approved values.
  - **Specifications:** each document is created once in the target with its files and attached to every copied item that had it. The widget downloads the files from the source and hands them to the service.

  The preview shows them in an **Associated** column. The dry run marks each one new, reuse, link, missing or waiting. Items reused from the target keep their own associations.

The widget only reads from the source tenant. All writing to the target is done by the service, with the same code as the `mbom_copy.py` script.

## Add it to a dashboard
Add it to a dashboard in the **source** tenant, using either of these:
- **URL:** in "Run Your App", enter `https://joseph-aj-1.github.io/Experiments/mbom-copier/index.html`.
- **Upload:** upload `index.html`. It is a small loader that pulls everything else from GitHub Pages.

## Start the service on your PC (each time)
```powershell
cd C:\MCP\mcp-servers\mbom-copier
.\.venv\Scripts\python.exe mbom_service.py
```
The window shows the **pairing token**. Leave the window open while you use the widget.

## Settings (⚙, once)
1. **Service on this PC:** keep the address `http://127.0.0.1:8765`, paste the pairing token, then click **Save & check**.
2. **Target tenant:** fill in the tenant address (any Lighthouse URL), your 3DPassport username and password, the security context (internal names), and the agent key. Then click **Test connection**.

The service saves these in `target.env` on your PC, in the same format as the script uses. The password and agent key are never sent back to the browser. The browser itself keeps only the service address and the pairing token, in its local storage and not in the dashboard.

## "Service not reachable" while the service is running
Recent Chrome and Edge versions ask before a website may reach a service on your own PC (**local network access**).
- **A prompt appears:** click **Allow**.
- **No prompt appears, or the setting is blocked:** this can happen inside the dashboard, because the widget runs in a frame.
  - Check the site settings from the lock icon in the address bar.
  - If your company manages Chrome or Edge, IT can allow it with the `LocalNetworkAccessAllowedForUrls` policy for `https://*.3dexperience.3ds.com` and `https://joseph-aj-1.github.io`.
  - In the meantime, the `mbom_copy.py` script does the same copy from PowerShell.

## How it is put together
```
mbom-copier/
├── index.html        loader (reads manifest.json, loads css/js from GitHub Pages)
├── manifest.json     version + files in load order
├── css/mbom-copier.css
├── js/
│   ├── core.js       namespace (window.MBC), helpers, WAFData requests, security context
│   ├── ui.js         layout, structure table, button states
│   ├── source.js     search / drop, read the structure (dsmfg, Details masks), preview rows
│   ├── service.js    calls to the local service, Settings screen
│   ├── copy.js       Dry run, two-click Copy, progress polling
│   └── main.js       MBC.start(): platform modules, 3DSpace, context, events, drag & drop
└── test/             end-to-end test: mocked dashboard + real local service + mock target
```
After a change, bump `version` in manifest.json.

## Service API (127.0.0.1 only)
Every call needs the `X-MBC-Token` header. Calls from a web page must come from an allowed origin (`allowed_origins` in `service.json`).

| Call | Does |
| --- | --- |
| `GET /status` | Version and target summary (no secrets) |
| `GET/POST /settings` | Read or update `target.env`. A blank password or key keeps the stored one. |
| `POST /settings/test` | Signs in to the target and runs a search |
| `POST /plan` | `{source_tenant, root, items, children, reuse_existing, title_suffix}` → plan rows, counts, warnings, run id. Nothing is written. |
| `POST /execute` | `{run}` → starts the copy in the background |
| `GET /runs/{run}` | Progress: status, rows, events, verification |
| `GET /runs` | Recent runs |

## Tests
```
pip install playwright && python -m playwright install chromium
python test/run_test.py
```
The test runs 30 checks across preview, settings, dry run, copy, verification and security.
