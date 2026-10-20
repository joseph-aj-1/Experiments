"""OAuth for remote (HTTP) mode, e.g. when deployed to Cloud Run.

Only used when TDX_AUTH=github. stdio mode (Claude Desktop / Claude Code)
never touches this file.

Why GitHub OAuth plus an allowlist:
  claude.ai custom connectors connect from Anthropic's cloud, so the
  server's URL is public. Without auth, anyone who found the URL could
  act on the 3DEXPERIENCE tenant with *your* 3DPassport login. GitHub
  OAuth proves who is calling; TDX_ALLOWED_GITHUB_USERS limits it to you
  (and anyone you explicitly add).

Environment variables:
  TDX_AUTH                   "github" to enable (anything else = no auth)
  TDX_PUBLIC_URL             the server's public https URL, no trailing slash
                             (e.g. https://tdx-mcp-xxxx.europe-west1.run.app)
  GITHUB_CLIENT_ID           from your GitHub OAuth App
  GITHUB_CLIENT_SECRET       from your GitHub OAuth App
  TDX_ALLOWED_GITHUB_USERS   comma-separated GitHub logins, e.g. "joseph-aj-1"
  TDX_JWT_SIGNING_KEY        long random string; keeps issued tokens and stored
                             OAuth state valid across restarts
  FASTMCP_HOME               where OAuth state is stored; point it at a
                             persistent volume (Cloud Run: a GCS bucket mount)
"""
from __future__ import annotations

import logging
import os

from fastmcp.server.auth.providers.github import GitHubProvider, GitHubTokenVerifier

logger = logging.getLogger("tdx_mcp.auth")


class _AllowlistVerifier(GitHubTokenVerifier):
    """GitHub token check that also requires the login to be allowlisted."""

    def __init__(self, inner: GitHubTokenVerifier, allowed: set[str]) -> None:
        # Reuse the configured inner verifier's settings.
        self.__dict__.update(inner.__dict__)
        self._allowed = allowed

    async def verify_token(self, token: str):  # type: ignore[override]
        result = await super().verify_token(token)
        if result is None:
            return None
        login = str((result.claims or {}).get("login", "")).lower()
        if login not in self._allowed:
            logger.warning("Rejected GitHub user '%s' (not in TDX_ALLOWED_GITHUB_USERS)", login)
            return None
        return result


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"TDX_AUTH=github needs {name} to be set")
    return value


def build_auth():
    """Return a FastMCP auth provider, or None when remote auth is off."""
    mode = os.getenv("TDX_AUTH", "").strip().lower()
    if mode != "github":
        return None

    allowed = {
        u.strip().lower()
        for u in _require("TDX_ALLOWED_GITHUB_USERS").split(",")
        if u.strip()
    }
    if not allowed:
        raise RuntimeError("TDX_ALLOWED_GITHUB_USERS is empty; refusing to start an open server")

    provider = GitHubProvider(
        client_id=_require("GITHUB_CLIENT_ID"),
        client_secret=_require("GITHUB_CLIENT_SECRET"),
        base_url=_require("TDX_PUBLIC_URL").rstrip("/"),
        jwt_signing_key=_require("TDX_JWT_SIGNING_KEY"),
        # Only accept OAuth redirects back to Claude.
        allowed_client_redirect_uris=[
            "https://claude.ai/api/mcp/auth_callback",
            "https://claude.com/api/mcp/auth_callback",
        ],
        cache_ttl_seconds=300,
    )
    provider._token_validator = _AllowlistVerifier(provider._token_validator, allowed)
    logger.info("GitHub OAuth enabled for: %s", ", ".join(sorted(allowed)))
    return provider
