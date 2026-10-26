# MBOM Copier

This tool copies a Manufacturing Item structure (MBOM) from one 3DEXPERIENCE tenant to another, for example from OI000629352 (eu1 demo) to Lighthouse (R1132100000770, us1).

By default it is a **dry run**. It reads the source, checks the target and prints what it would create, and writes nothing. It only writes when you add `--execute`, and it never writes to the source.

## Get started with the widget (colleagues: start here)

The widget runs in your 3DDashboard. It needs this small service running on **your** PC, signed in to the target tenant as **you**. Nothing is shared between colleagues: everyone has their own settings, token and run records.

**1. Get the folder.** Clone it from GitLab, or download it as a zip and unzip it to `C:\MCP\mbom-copier`. If you were given `mbom-copier-service.exe`, put it in the same folder; then you don't need Python.

**2. Install.** In PowerShell, from that folder:
```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```
This:
- sets up Python (or uses the `.exe`);
- picks a free local port;
- makes the service start automatically at sign-in, and starts it now;
- prints the **address** and **pairing token**, with the token copied to your clipboard.

No admin rights are needed.

**3. Add the widget.** In your source tenant's dashboard, use **Run Your App** with `https://joseph-aj-1.github.io/Experiments/mbom-copier/index.html`.

**4. Pair it and set the target.** In the widget, open **⚙ Settings**:
- paste the address and token, then press **Save & check**;
- fill in the target tenant address, your 3DPassport login, your security context (internal names, e.g. `VPLMProjectLeader.Company Name.Common Space`) and the agent key;
- press **Test connection**.

If the browser asks to allow access to devices on your local network, allow it.

**5. Use it.** Drop a Manufacturing Item, tick what else to copy, run **Dry run**, check the plan, then **Copy**.

| Later | Command |
| --- | --- |
| Show the address and token again | `.\install.ps1 -Info` |
| Update | get the new files (`git pull`, or unzip over the folder; your settings are kept), then run `.\install.ps1` again |
| Stop and remove the auto-start | `.\install.ps1 -Uninstall` (your files are kept) |
| Something fails | check `service.log` (the service) and `auth_debug.log` (sign-in) in this folder |

**"Service not reachable" while it is running:**
- The browser is blocking local network access. Allow it from the lock icon in the address bar, or ask IT for the `LocalNetworkAccessAllowedForUrls` policy for `https://*.3dexperience.3ds.com` and `https://joseph-aj-1.github.io`.
- Or the port changed. Run `-Info` and update the address in Settings.

## Share with colleagues (maintainer)

- **Code:** push this folder to the company GitLab, as with the Configured MBOM Builder. `.gitignore` keeps personal files out: `*.env`, `service.json`, `runs\`, logs.
- **No-Python option:** run `.\build_exe.ps1` once on a Windows PC to get `mbom-copier-service.exe`. Attach it to a GitLab release, or put it on a shared drive. Don't commit it. Colleagues put it next to `install.ps1`.
- **The widget** needs no sharing: everyone uses the same GitHub Pages URL, and it updates itself.

## Command-line script (structure only)

The script below copies the structure without the widget, using `source.env` and `target.env`.

## Setup (once)

```powershell
cd E:\MCP\Experiments\mcp-servers\mbom-copier
pip install -r requirements.txt
copy source.env.example source.env    # or copy your tdx-mcp-server .env
copy target.env.example target.env
```

Fill in `target.env` for Lighthouse:

| Key | What to put |
| --- | --- |
| `TDX_USERNAME` / `TDX_PASSWORD` | Your Lighthouse 3DPassport login |
| `SecurityContext` | The role.organization.collaborative space you work in on Lighthouse, as shown in the role menu. It must be allowed to create Manufacturing Items. |
| `APIKey` | The **key** of the MCPAgent agent in Lighthouse's Agent Management. Use the key, not the agent ID. |

The tenant URLs are already filled in.

## Run

```powershell
# 1. Dry run: prints the plan and saves it in runs\
python mbom_copy.py "AJ MA 101"

# 2. Copy (asks you to type yes)
python mbom_copy.py "AJ MA 101" --execute

#    or create exactly the plan from step 1
python mbom_copy.py --resume runs\<file>.json --execute
```

You can identify the source item by its physical ID, its exact title, or its name. If a title matches several items, the tool lists them with their IDs and stops.

| Option | Effect |
| --- | --- |
| `--reuse-existing` | If the target already has exactly one item with the same title and type, the copy uses it instead of creating a new one. The reused item's own structure is left untouched, and items used only inside it are not copied. |
| `--title-suffix " (copy)"` | Adds the suffix to every created title. Useful for a trial copy into the same tenant. |
| `--source` / `--target` | Use other env files, for example to copy in the other direction. |
| `--yes` | Skips the confirmation prompt. |

## With the widget

The [MBOM Copier widget](../../mbom-copier/) does the same copy from a 3DDashboard. You drop the item, see a preview of the structure, then run Dry run and Copy. It talks to a small service on this PC:

```powershell
.\.venv\Scripts\python.exe mbom_service.py
```

- The service listens on 127.0.0.1:8765 and prints a pairing token the first time it starts. The token is kept in `service.json`.
- The widget reads the source with your dashboard sign-in, so `source.env` isn't used.
- The widget's Settings screen writes `target.env`.
- The service writes the same `runs\*.json` records as the script, so a run started in one can be finished in the other.

Associated objects (Change Actions, Plants, MEIs, Specifications) are copied through the widget only; `assoc.py` holds that part. The script copies the structure itself.

## What it does

1. **Reads** the whole structure below the root on the source, with the Details masks. Shared sub-assemblies are read once.
2. **Checks the target** by searching for every title (plus the suffix) and type. Items that already exist are flagged; with `--reuse-existing` they are reused.
3. **Prints the plan**: the tree with CREATE / REUSE / — per row, the counts, and warnings. Warnings cover continuous items with no readable quantity and copies into the same tenant.
4. With `--execute`, it **creates every item first**, then each parent's **instances one by one in source BOM order**. A sub-assembly used in two places is created once and instanced twice.
5. **Verifies**: it reads every new parent back from the target and compares child counts with the source.

Every success is written to the run record (`runs\*.json`) straight away. If a run stops because of a throttle, a lost session or a refused item, fix the cause and run `--resume <record> --execute`. Finished steps are skipped and nothing is created twice. Items that a run created but that were later deleted are found missing and created again.

### Copied
- **Items:** type, title, description, part number, planning required and outsourced.
- **Instances:** description, plus quantity and its tolerances for continuous items.

### Not copied
- Scope and implement links to engineering
- MEIs and Sourcing qualifications
- Configuration and effectivity
- Specification documents
- Revisions, maturity states and change objects

New items get the target's own autonames and start In Work.

## Notes
- The sign-in code in `app/` is the same as in tdx-mcp-server: 3DPassport login, then the APIGateway with the agent key. If sign-in fails, `auth_debug.log` has the trace.
- Lighthouse (us1) and the demo tenant (eu1) use different 3DPassport regions, so the two logins are kept apart. Two *different* users on the *same* 3DPassport cannot be used in one run.
- The search index on the target can lag by about a minute. An item created moments earlier may not be found by `--reuse-existing` yet.

## Tests

```
python tests/test_copy.py
python tests/test_service.py
python tests/test_assoc.py
```

This runs 23 checks against two in-memory tenants:
- the dry run writes nothing;
- ambiguous roots are refused;
- a failure partway through is resumed without duplicates;
- the copy has the same structure and BOM order as the source;
- attributes and continuous quantity are copied;
- reuse works;
- suffix and same-tenant warnings appear.
