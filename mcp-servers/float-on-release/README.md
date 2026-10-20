# Float on Release

When a Manufacturing Item revision is **released**, Float on Release finds every
instance of its **older revisions** in the item's **immediate parent** MBOMs and
re-points those instances to the released revision with the dsmfg `replace` API.

```
EIF "Status Change" event ─▶ eif-listener  (saves events\*.json; unchanged)
                                   │
                                   ▼
                     Float on Release agent (agent.py, or server.py --watch)
                       1. Manufacturing Item + status-change event?  (else ignore)
                       2. item's live state == RELEASED?             (else ignore)
                       3. older revisions = same name & type, created earlier
                       4. where-used: dsmfg:MfgItemInstance/locate (target)
                       5. for each parent in an allowed state:
                          POST dsmfg:MfgItem/{parent}/dsmfg:MfgItemInstance/{inst}/replace
                       6. log to logs\runs.jsonl
```

It uses the **Owner** role (`VPLMProjectAdministrator.Company Name.Common Space`),
so released parents are updated in place without a new parent revision.
Login, APIKey and CSRF come from the existing `tdx-mcp-server` (its `.env`);
Float on Release has no credentials of its own.

## Folder layout

Put this folder next to the other two projects:

```
E:\MCP\Experiments\
  tdx-mcp-server\      (auth + .env, reused)
  eif-listener\        (receives events, unchanged)
  float-on-release\    (this project)
```

## config.json

| Setting | Default | Meaning |
|---|---|---|
| `security_context` | `VPLMProjectAdministrator.Company Name.Common Space` | Role used for every call (Owner). |
| `dry_run` | `true` | Log what would be replaced and change nothing. **Set to `false` to go live.** |
| `editable_parent_states` | PRIVATE, IN_WORK, FROZEN, RELEASED | Parents in other states (OBSOLETE) are skipped and reported. |
| `status_event_types` | `[]` (auto-detect) | Exact EIF `eventType` values that mean "status change". Fill this in after you see the real event. |
| `events_dir` | `../eif-listener/events` | Where the listener saves events. |
| `process_existing_events` | `false` | On the first start, events already in the folder are history and are not processed. |
| `change_action_id` | `""` | Optional Change Action physical ID, sent as `DS-Change-Authoring-Context` if parents are under change control. |

## Run the automatic agent

1. Start the EIF listener: `..\eif-listener\run.ps1`. Enable the Manufacturing Item **Status Change** event for the agent in the EIF settings.
2. In a second window: `.\run-agent.ps1`. On first run this creates `.venv` and installs the requirements.

Every event the agent sees is written to `logs\events_seen.log` with its `eventType` and whether it matched. Use this to confirm the real status-change `eventType`, then put it in `status_event_types`. Each run, automatic or manual, is appended to `logs\runs.jsonl`.

## Use it as an MCP server (Claude Desktop)

Add to `claude_desktop_config.json`:

```json
"float-on-release": {
  "command": "E:\\MCP\\Experiments\\float-on-release\\.venv\\Scripts\\python.exe",
  "args": ["E:\\MCP\\Experiments\\float-on-release\\server.py"]
}
```

Tools: `preview_float_on_release(item)`, `float_on_release(item, apply)`,
`handle_eif_event(event_json)`, `recent_float_runs(limit)`, `float_on_release_settings()`.
`item` can be a physical ID or a title such as `AJ PP 301`.

To have one long-running process do both, the tools and the automatic agent, run
`python server.py --http --watch`. The tools are then served at `http://127.0.0.1:8010/mcp`. Run either this or `run-agent.ps1`, not both.

## Test with AJ PP 301

1. `.\.venv\Scripts\python agent.py --item "AJ PP 301"` gives a dry-run preview. Before rev B is released, it reports "not released".
2. With `run-agent.ps1` and the listener running, release **AJ PP 301 rev B**.
3. `logs\runs.jsonl` should show AJ MA 300 (instance `AJ PP 301.0`) planned A → B, as a dry run.
4. Set `"dry_run": false`. Then either release the next test item, or run `agent.py --item "AJ PP 301" --apply`, and check AJ MA 300 in 3DEXPERIENCE.
