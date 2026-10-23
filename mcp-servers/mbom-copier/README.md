# MBOM Copier

This tool copies a Manufacturing Item structure (MBOM) from one 3DEXPERIENCE tenant to another, for example from OI000629352 (eu1 demo) to Lighthouse (R1132100000770, us1).

By default it is a **dry run**. It reads the source, checks the target and prints what it would create, and writes nothing. It only writes when you add `--execute`, and it never writes to the source.

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
```

This runs 23 checks against two in-memory tenants:
- the dry run writes nothing;
- ambiguous roots are refused;
- a failure partway through is resumed without duplicates;
- the copy has the same structure and BOM order as the source;
- attributes and continuous quantity are copied;
- reuse works;
- suffix and same-tenant warnings appear.
