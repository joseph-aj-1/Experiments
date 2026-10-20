# EIF event capture (eif-listener)

Listens to the tenant's 3DEXPERIENCE EIF event topic and saves every event as a JSON file
in `events\`. First use: capture the payload of the **Manufacturing Item versioned** event.
Later, this becomes the trigger for the Sourcing agent.

## One-time setup

1. Install a .NET SDK (7 or newer) if `dotnet --version` doesn't work:
   `winget install Microsoft.DotNet.SDK.8`
2. Edit `config.json`:
   - `JmsUrl`: your tenant's EIF broker address (from EIF / your platform admin / Dassault support)
   - `AgentId`: the ID of **MCPAgent** shown in Agent Management (an ID, not the display name)
   - `TenantId`: already set to `OI000629352`
   - `Topic`: leave empty to use `3dsevents.<TenantId>.3DSpace.user`

## Run

```powershell
cd E:\MCP\Experiments\eif-listener
.\run.ps1
```

It asks for the MCPAgent API key (input is hidden and nothing is saved). When it prints
`Connected`, revise a Manufacturing Item in the sandbox. Each event appears as one line in the
console and as a file such as `events\20261013-131500-123_0001.json`. Press Ctrl+C to stop.

The subscription is durable: events published while the listener is stopped are delivered the
next time it starts with the same AgentId.

If PowerShell blocks the script, run it once with:
`powershell -ExecutionPolicy Bypass -File .\run.ps1`

## Troubleshooting

| Message | Likely cause |
|---|---|
| `Could not connect or subscribe ... authentication` | Wrong AgentId or API key, or the agent isn't allowed to consume events |
| Connects but nothing arrives | The event isn't published to this topic, or the revision didn't trigger it. Check the Event Publishing app |
| `InvalidClientIDException` | Another listener is already running with the same agent. Close it first |

The secret can also be supplied via the `EIF_AGENT_SECRET` environment variable, or a local
`agent.secret` file (git-ignored). Never put it in `config.json`.
