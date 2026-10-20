# Configured MBOM Builder

Builds a **configured Manufacturing BOM** in 3DEXPERIENCE from an Excel template, through Claude Desktop.

From one workbook it creates:

- the **Portfolio** model version, variant and variant values (allocated to the model version)
- the **Manufacturing Items** (or reuses existing ones) and the **instances** (quantity N = N instances)
- the **configuration context** (model attached from the top item down to the configured item, Variant criterion enabled)
- the **variant effectivity** on every variant-specific line

Then it **reads everything back** and confirms each variant value resolves to the lines the sheet expects.

## Get it from GitLab

Project: <https://itgit.dsone.3ds.com/HJH/configured-mbom-builder> (private; ask the owner to add you
as a member with the **Reporter** role).

**Option A: Clone** (recommended; updates are then one command)

```powershell
cd C:\MCP
git clone https://itgit.dsone.3ds.com/HJH/configured-mbom-builder.git
```

If Git asks for a password, use a GitLab **personal access token** (scope `read_repository`), not your
normal password.

**Option B: Download**: on the project page, **Code → Download source code → zip**, and unzip it to
`C:\MCP\configured-mbom-builder`.

Then follow **Install** below.

### Updates

If you cloned: `cd C:\MCP\configured-mbom-builder`, then `git pull`, then restart Claude Desktop.
Your `.env` and `.venv` are not touched (Git ignores them). If you downloaded the zip, download it again
and copy your `.env` into the new folder.

## Install (once per PC)

1. Put this folder somewhere permanent, e.g. `C:\MCP\configured-mbom-builder` (see **Get it from GitLab**).
2. In PowerShell, in that folder: `powershell -ExecutionPolicy Bypass -File .\install.ps1`
   (installs Python packages into `.venv` and creates `.env`).
3. Open `.env` and fill in your 3DEXPERIENCE sign-in, role (SecurityContext), API Gateway key and tenant addresses.
4. Add the entry the installer printed to `%APPDATA%\Claude\claude_desktop_config.json` under `"mcpServers"`.
5. Quit Claude Desktop completely (also from the system tray) and start it again.

Optional check without touching 3DEXPERIENCE: `.\.venv\Scripts\python tests\test_builder.py`

Requirements: Windows, Python 3.10+, Claude Desktop, a 3DEXPERIENCE account with username/password sign-in
(SSO-only tenants are not supported) and a role allowed to create Manufacturing Items and Portfolio objects.

## Use

In Claude Desktop:

1. **"Create a blank configured MBOM template at C:\Work\MyProduct.xlsx"**, or copy
   `templates\Example_R648_Housing.xlsx` (a complete worked example).
2. Fill it in (the Instructions tab explains every column). The Check column must say OK on every row.
3. **"Preview the configured MBOM in C:\Work\MyProduct.xlsx"**: Claude shows what will be created,
   lines per variant value, and any problems (in the sheet or in the tenant). Nothing is changed.
4. **"Build it"**: only after you approve the preview.
5. Open the top item in 3DEXPERIENCE and filter by the model and a variant value.

Other requests: "list my configured MBOM builds", "validate the last build again".

If a build stops part-way (network, permissions), fix the cause and ask Claude to **resume** that run:
everything already created is reused, nothing is duplicated.

## The template

| Tab | What goes in it |
|---|---|
| Model | Model version title and revision, the item the model is attached to, the configured item, the variant name, and up to 6 values (one per X column) |
| Structure | One row per line: Level, Part number, Title, Description, Type, UOM, Qty, Qty note, Item source (New/Existing), Existing ID, X per variant value |

- X marks go only on **direct children of the configured item**. X in every column = common part (no effectivity).
- Quantity above 1 becomes that many instances. Consumables: Qty 1 and "As required" in Qty note.
- A model version title that already exists stops the build, so the same workbook cannot be built twice by accident.

## Files

| Path | Purpose |
|---|---|
| `server.py` | The MCP server Claude Desktop starts |
| `cmb/template.py` | Reads and checks the workbook; creates templates |
| `cmb/builder.py` | Builds in 3DEXPERIENCE, records every object, validates |
| `app/` | 3DEXPERIENCE sign-in and API client (3DPassport, API Gateway, CSRF), from the tdx-mcp-server project |
| `templates/` | Blank template, R-648 example, and a 5-line mini test |
| `runs/` | One record per build with every created ID (used for resume and validation) |
| `tests/` | Offline tests against a simulated tenant |

## What it creates, in 3DEXPERIENCE terms

| Step | Web service |
|---|---|
| Model version (type Hardware Product), variant, values, allocation | `dspfl` ModelVersion, Variant, VariantValue, VariantInstance |
| Items / instances | `dsmfg` MfgItem create, MfgItemInstance create |
| Configuration context | `dsmfg` dscfg:Configured attach; PATCH enabledCriteria ["Variant"] on the configured item |
| Effectivity | `dsmfg` …/dscfg:Filterable/set/variant (CfgEffectivityExpression XML, OR for several values) |
| Validation | `dsmfg` MfgItemInstance list, …/dscfg:Filterable read |

Limits of this version: one variant per model (several values), effectivity on the configured item's direct
children, no evolution effectivity, no Change Action context. Built items are IN_WORK.

## Before sharing more widely

- All data calls use Dassault's documented 3DEXPERIENCE web services (dsmfg, dspfl).
- The sign-in imitates the 3DPassport browser login with the username and password in `.env`. It is not a
  published API: it can break if Dassault changes the login page, and it does not work on SSO-only tenants.
- Confirm with your 3DEXPERIENCE administrator that automated use through personal accounts is acceptable,
  and which authentication method shared tools should use. Only the sign-in code in `app/` would change.
