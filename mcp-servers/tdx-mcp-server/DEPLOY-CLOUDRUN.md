# Deploying tdx-mcp-server to Cloud Run (remote MCP for claude.ai)

Result: a public HTTPS endpoint `https://<service>.run.app/mcp` that you add
as a **custom connector** on claude.ai. It then works in any browser,
including Chrome on your company laptop (as long as claude.ai is reachable there).

Local stdio mode for Claude Desktop is unchanged: `python server.py` still works.

## What changed in the code

| File | Change |
|---|---|
| `server.py` | `--http` reads `$PORT`, turns on OAuth when `TDX_AUTH=github`, runs stateless; warns if exposed without auth |
| `app/remote_auth.py` | **new** GitHub OAuth, restricted to `TDX_ALLOWED_GITHUB_USERS`; only Claude's redirect URLs accepted |
| `app/loader.py` | drops proxy/trace/MCP headers that FastMCP would otherwise forward to 3DEXPERIENCE |
| `app/config.py` | `TDX_ENV_FILE` lets the `.env` come from a mounted secret |
| `requirements.txt` | `fastmcp` pinned to 4.0.10 (the version this was tested against) |
| `Dockerfile`, `.dockerignore` | container image; `.env`, `.venv`, logs, widgets etc. are never copied in |
| `.gitignore` | keeps `.env` and logs out of Git |

How it is secured:
1. claude.ai calls `/mcp` → 401 → OAuth discovery → you sign in with **GitHub**.
2. The server checks your GitHub login against `TDX_ALLOWED_GITHUB_USERS`. Anyone else is rejected.
3. Calls then go to 3DEXPERIENCE with **your** 3DPassport credentials from the secret, exactly like today.

> Because every allowed user acts as *you* in 3DX, keep the allowlist to yourself.
> Sharing with colleagues needs per-user 3DPassport login (a later step).

---

## 0. One-time prerequisites

1. **Google Cloud account** with billing enabled, and the
   [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed.
2. In PowerShell:

```powershell
gcloud auth login
gcloud projects create tdx-mcp-<something-unique>     # or reuse an existing project
gcloud config set project tdx-mcp-<something-unique>
gcloud config set run/region europe-west1              # close to the EU1 tenant
gcloud services enable run.googleapis.com cloudbuild.googleapis.com `
    secretmanager.googleapis.com artifactregistry.googleapis.com storage.googleapis.com
```

## 1. First deploy (to get the URL)

From `E:\MCP\Experiments\tdx-mcp-server`:

```powershell
gcloud run deploy tdx-mcp --source . --allow-unauthenticated `
    --max-instances 1 --memory 1Gi `
    --set-env-vars "TDX_AUTH=off,TDX_APIGATEWAY_URL=https://oi000629352-eu1-apigateway.3dexperience.3ds.com,TDX_BASE_URL=https://oi000629352-eu1-space.3dexperience.3ds.com/enovia"
```

(Use the same two URLs as in your `.env` if they differ.)

`--allow-unauthenticated` only means Google doesn't add *its* login in front;
your GitHub OAuth does that job. With `TDX_AUTH=off` and no secrets, this first
revision has **no 3DX credentials**, so it is harmless while you finish setup.

Note the URL it prints, e.g. `https://tdx-mcp-abc123-ew.a.run.app`.

## 2. Create a GitHub OAuth App

GitHub → Settings → Developer settings → **OAuth Apps** → New OAuth App

- Application name: `tdx-mcp`
- Homepage URL: `https://tdx-mcp-abc123-ew.a.run.app`
- Authorization callback URL: `https://tdx-mcp-abc123-ew.a.run.app/auth/callback`

Copy the **Client ID** and generate a **Client secret**.

## 3. Put all secrets in one Secret Manager secret

Make a copy of your `.env` (e.g. `tdx-cloud.env`, **outside** the repo folder)
and append:

```ini
GITHUB_CLIENT_ID=Ov23li...
GITHUB_CLIENT_SECRET=...
TDX_ALLOWED_GITHUB_USERS=joseph-aj-1
TDX_JWT_SIGNING_KEY=<paste a long random string>
```

Generate the random string with:

```powershell
-join ((1..48) | ForEach-Object { [char](Get-Random -Minimum 33 -Maximum 126) })
```

Check the file only points at the **oi000629352** tenant, then:

```powershell
gcloud secrets create tdx-mcp-env --data-file=C:\path\to\tdx-cloud.env
```

Then delete the copy. Later changes: `gcloud secrets versions add tdx-mcp-env --data-file=...`

Let Cloud Run read it:

```powershell
$PROJECT_NUMBER = gcloud projects describe (gcloud config get-value project) --format="value(projectNumber)"
gcloud secrets add-iam-policy-binding tdx-mcp-env `
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" `
    --role="roles/secretmanager.secretAccessor"
```

## 4. Bucket for OAuth state

Keeps claude.ai's connector registration alive across cold starts and redeploys.

```powershell
gcloud storage buckets create gs://tdx-mcp-oauth-<unique> --location=europe-west1 --uniform-bucket-level-access
gcloud storage buckets add-iam-policy-binding gs://tdx-mcp-oauth-<unique> `
    --member="serviceAccount:$PROJECT_NUMBER-compute@developer.gserviceaccount.com" `
    --role="roles/storage.objectAdmin"
```

## 5. Real deploy

```powershell
$URL = "https://tdx-mcp-abc123-ew.a.run.app"
gcloud run deploy tdx-mcp --source . --allow-unauthenticated `
    --max-instances 1 --memory 1Gi --execution-environment gen2 `
    --set-env-vars "TDX_AUTH=github,TDX_PUBLIC_URL=$URL,TDX_ENV_FILE=/secrets/tdx.env,FASTMCP_HOME=/data/fastmcp" `
    --set-secrets "/secrets/tdx.env=tdx-mcp-env:latest" `
    --add-volume "name=oauth,type=cloud-storage,bucket=tdx-mcp-oauth-<unique>" `
    --add-volume-mount "volume=oauth,mount-path=/data"
```

`--max-instances 1` matters: the 3DPassport session (cookie jar) lives in one process.

Check it is locked:

```powershell
curl.exe -i -X POST "$URL/mcp" -H "content-type: application/json" -d "{}"
# expect: HTTP/1.1 401 Unauthorized
```

## 6. Add it in claude.ai

claude.ai → **Customize → Connectors → Add custom connector**

- Name: `3DEXPERIENCE`
- URL: `https://tdx-mcp-abc123-ew.a.run.app/mcp`

Click **Connect** → approve the consent screen → sign in with GitHub. In a chat,
enable the connector from the tools menu and ask something like
"search Manufacturing Items named MA-101".

## Troubleshooting

- **Logs:** `gcloud run services logs read tdx-mcp --limit 100`
- **"Rejected GitHub user"** in the logs: your login isn't in `TDX_ALLOWED_GITHUB_USERS`.
- **3DPassport login fails from the cloud** (works locally): 3DPassport may challenge
  logins from unfamiliar Google IPs. Check the log trace, and try an API-key or
  agent-based auth from the gateway instead of username and password.
- **Slow first call:** cold start plus the 3DPassport login, usually 5–15 s. Add
  `--min-instances 1` to keep it warm (costs a little).
- **Too many tools:** claude.ai handles a large toolset less well than a curated one.
  Use `exclude_operation_ids` in `config/services.yaml` to trim the remote deployment.

## Optional: GitLab CI

Push the repo (without `.env`) to GitLab, and have a pipeline run the same
`gcloud run deploy ... --source .` step with a Google service-account key in a
masked CI/CD variable. Secrets stay in Secret Manager; the pipeline only ships code.
