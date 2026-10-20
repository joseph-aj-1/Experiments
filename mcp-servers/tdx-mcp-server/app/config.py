"""Loads environment credentials and the services.yaml registry."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
SPECS_DIR = ROOT / "specs"
SERVICES_FILE = ROOT / "config" / "services.yaml"

# TDX_ENV_FILE lets a deployment point at a mounted secret (e.g. Cloud Run
# Secret Manager volume at /secrets/tdx.env); local runs keep using ./.env.
load_dotenv(os.getenv("TDX_ENV_FILE") or (ROOT / ".env"))


@dataclass
class Credentials:
    """3DEXPERIENCE credentials shared by every mounted webservice."""

    authorization: str = field(default_factory=lambda: os.getenv("Authorization", ""))
    security_context: str = field(default_factory=lambda: os.getenv("SecurityContext", ""))
    api_key: str = field(default_factory=lambda: os.getenv("APIKey", ""))
    base_url: str = field(default_factory=lambda: os.getenv("TDX_BASE_URL", ""))
    apigateway_url: str = field(default_factory=lambda: os.getenv("TDX_APIGATEWAY_URL", ""))
    server_preference: str = field(
        default_factory=lambda: os.getenv("TDX_SERVER_PREFERENCE", "3DSpace")
    )
    verify_ssl: bool = field(
        default_factory=lambda: os.getenv("TDX_VERIFY_SSL", "true").lower() != "false"
    )
    timeout_seconds: float = field(
        default_factory=lambda: float(os.getenv("TDX_TIMEOUT_SECONDS", "30"))
    )

    # --- 3DPassport (CAS) login -------------------------------------------
    # Set TDX_USERNAME + TDX_PASSWORD to have the server sign in to
    # 3DPassport at startup and reuse the session cookies on every call.
    # TDX_PASSPORT_URL is optional: it is discovered from the login redirect
    # if omitted (e.g. https://<tenant>.iam.3dexperience.3ds.com).
    username: str = field(default_factory=lambda: os.getenv("TDX_USERNAME", ""))
    password: str = field(default_factory=lambda: os.getenv("TDX_PASSWORD", ""), repr=False)
    passport_url: str = field(default_factory=lambda: os.getenv("TDX_PASSPORT_URL", ""))
    # Platform tenant ID (e.g. OI000629352). Sent as ?tenant= on every
    # 3DSpace call; if empty it is derived from the TDX_BASE_URL host name.
    tenant: str = field(default_factory=lambda: os.getenv("TDX_TENANT", ""))
    # 3DSpace root used for the 3DPassport ticket hand-off. Only needed when
    # TDX_BASE_URL points at the API gateway; derived automatically otherwise
    # (<tenant>-<region>-apigateway... -> <tenant>-<region>-space.../enovia).
    space_url: str = field(default_factory=lambda: os.getenv("TDX_SPACE_URL", ""))

    @property
    def use_passport(self) -> bool:
        return bool(self.username and self.password)

    def default_headers(self) -> dict[str, str]:
        """Only include headers that are actually configured."""
        headers = {}
        # A static Authorization header conflicts with a 3DPassport session,
        # so it is only sent when passport login is not configured.
        if self.authorization and not self.use_passport:
            headers["Authorization"] = self.authorization
        if self.security_context:
            headers["SecurityContext"] = self.security_context
        if self.api_key:
            headers["APIKey"] = self.api_key
        return headers


@dataclass
class ServiceEntry:
    name: str
    file: str
    enabled: bool = True
    prefix: str | None = None
    server_preference: str | None = None
    exclude_tags: list[str] = field(default_factory=list)
    exclude_operation_ids: list[str] = field(default_factory=list)
    exclude_paths: list[str] = field(default_factory=list)
    # operationId -> short tool name (FastMCP mcp_names); avoids cut-off names
    tool_names: dict[str, str] = field(default_factory=dict)

    @property
    def spec_path(self) -> Path:
        return SPECS_DIR / self.file


def load_services() -> list[ServiceEntry]:
    if not SERVICES_FILE.exists():
        return []
    with open(SERVICES_FILE) as f:
        raw = yaml.safe_load(f) or {}
    entries = []
    for item in raw.get("services", []):
        entries.append(
            ServiceEntry(
                name=item["name"],
                file=item["file"],
                enabled=item.get("enabled", True),
                prefix=item.get("prefix"),
                server_preference=item.get("server_preference"),
                exclude_tags=item.get("exclude_tags", []) or [],
                exclude_operation_ids=item.get("exclude_operation_ids", []) or [],
                exclude_paths=item.get("exclude_paths", []) or [],
                tool_names={str(k): str(v) for k, v in (item.get("tool_names") or {}).items()},
            )
        )
    return entries


CREDENTIALS = Credentials()
