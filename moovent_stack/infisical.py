"""
Infisical integration: auth, scope resolution, and secret fetching.
"""

from __future__ import annotations

import json
import os
from typing import Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .config import (
    ACCESS_REQUEST_TIMEOUT_S,
    DEFAULT_INFISICAL_ENVIRONMENT,
    DEFAULT_INFISICAL_HOST,
    DEFAULT_INFISICAL_SECRET_PATH,
    INFISICAL_ENV_DEBUG,
    INFISICAL_ENV_CLIENT_ID,
    INFISICAL_ENV_CLIENT_SECRET,
    INFISICAL_ENV_ENVIRONMENT,
    INFISICAL_ENV_HOST,
    INFISICAL_ENV_PROJECT_ID,
    INFISICAL_ENV_SECRET_PATH,
    REQUIRED_INFISICAL_PROJECT_ID,
    _env_bool,
)
from .log import log_debug, log_error, log_info
from .storage import _load_config, _save_config


# Purpose: Cloudflare can block default Python urllib User-Agent (error 1010).
# We use a browser-like UA to avoid being fingerprinted as a bot.
_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _normalize_infisical_host(raw: Optional[str]) -> str:
    """Normalize Infisical host and ensure https:// is present."""
    value = (raw or "").strip()
    if not value:
        return DEFAULT_INFISICAL_HOST
    if value.startswith("http://") or value.startswith("https://"):
        return value.rstrip("/")
    return f"https://{value.rstrip('/')}"


def _resolve_infisical_settings() -> tuple[str, Optional[str], Optional[str]]:
    """
    Resolve Infisical Universal Auth settings.

    Priority:
    - environment variables
    - saved config file (~/.moovent_stack_config.json)
    """
    host = _normalize_infisical_host(os.environ.get(INFISICAL_ENV_HOST))
    env_client_id = os.environ.get(INFISICAL_ENV_CLIENT_ID, "").strip()
    env_client_secret = os.environ.get(INFISICAL_ENV_CLIENT_SECRET, "").strip()
    if env_client_id and env_client_secret:
        return host, env_client_id, env_client_secret

    cfg = _load_config()
    host = _normalize_infisical_host(
        str(cfg.get("infisical_host") or "").strip() or host
    )
    client_id = str(cfg.get("infisical_client_id") or "").strip()
    client_secret = str(cfg.get("infisical_client_secret") or "").strip()
    return host, (client_id or None), (client_secret or None)


def _normalize_infisical_secret_path(path: Optional[str]) -> str:
    """
    Ensure secret path is absolute to avoid accidental path mismatches.
    """
    value = (path or "").strip()
    if not value:
        return DEFAULT_INFISICAL_SECRET_PATH
    if not value.startswith("/"):
        return f"/{value}"
    return value


def _resolve_infisical_scope() -> tuple[str, str, str]:
    """
    Resolve the Infisical scope used for access validation.

    We intentionally enforce a single org + project for now.

    Returns:
    - project_id (required project UUID)
    - environment (default: dev)
    - secret_path (default: /)
    """
    # Project is fixed (single-project org).
    project_id = REQUIRED_INFISICAL_PROJECT_ID

    # Environment/path can be overridden to match your Infisical configuration.
    # This uses the same env var names as mqtt_dashboard_watch.
    cfg = _load_config()
    environment = (
        os.environ.get(INFISICAL_ENV_ENVIRONMENT)
        or str(cfg.get("infisical_environment") or "")
        or DEFAULT_INFISICAL_ENVIRONMENT
    ).strip() or DEFAULT_INFISICAL_ENVIRONMENT
    secret_path = _normalize_infisical_secret_path(
        os.environ.get(INFISICAL_ENV_SECRET_PATH)
        or str(cfg.get("infisical_secret_path") or "")
        or DEFAULT_INFISICAL_SECRET_PATH
    )
    return project_id, environment, secret_path


def _required_project_id_mismatch_reason() -> Optional[str]:
    """
    Enforce the required project ID if the user explicitly configured one.

    This avoids a footgun where a user points the stack at the wrong Infisical project
    and still passes Step 1.
    """
    cfg = _load_config()
    configured = (
        os.environ.get(INFISICAL_ENV_PROJECT_ID)
        or str(cfg.get("infisical_project_id") or "")
    ).strip()
    if configured and configured != REQUIRED_INFISICAL_PROJECT_ID:
        return "project_id_mismatch"
    return None


def _infisical_login(host: str, client_id: str, client_secret: str) -> Optional[str]:
    """
    Authenticate with Infisical Universal Auth and return access token.

    Returns:
    - access token string on success
    - None on failure
    """
    login_url = f"{host}/api/v1/auth/universal-auth/login"
    payload = {"clientId": client_id, "clientSecret": client_secret}
    body = json.dumps(payload).encode("utf-8")
    req = Request(login_url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("User-Agent", _DEFAULT_USER_AGENT)

    log_debug("infisical", f"POST {login_url} (universal-auth login)")

    try:
        with urlopen(req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8").strip()
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                log_error("infisical", f"Login response not a dict: {raw[:200]}")
                return None
            token = str(
                data.get("accessToken")
                or data.get("token")
                or data.get("access_token")
                or ""
            ).strip()
            if token:
                log_info("infisical", "Universal Auth login successful")
            else:
                log_error("infisical", f"No token in login response: {raw[:200]}")
            return token or None
    except HTTPError as err:
        try:
            body = err.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        log_error(
            "infisical",
            f"Login failed: HTTP {err.code} {err.reason} body={body[:300]}",
        )
        return None
    except Exception as exc:
        log_error("infisical", f"Login failed: {exc.__class__.__name__}: {exc}")
        return None


def _fetch_infisical_secrets(
    host: str, token: str, project_id: str, environment: str, secret_path: str
) -> dict[str, str]:
    """
    Fetch secrets from Infisical and return as dict.

    Returns:
    - dict of secret_key -> secret_value
    - empty dict on failure
    """
    from urllib.parse import urlencode

    query = urlencode(
        {
            "projectId": project_id,
            "environment": environment,
            "secretPath": secret_path,
            "expandSecretReferences": "true",
            "includeImports": "true",
            "recursive": "false",
        }
    )
    secrets_url = f"{host}/api/v4/secrets?{query}"
    secrets_req = Request(secrets_url, method="GET")
    secrets_req.add_header("Authorization", f"Bearer {token}")
    secrets_req.add_header("Accept", "application/json")
    secrets_req.add_header("User-Agent", _DEFAULT_USER_AGENT)

    try:
        with urlopen(secrets_req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8").strip()
            data = json.loads(raw) if raw else {}
            secrets_list = data.get("secrets", [])
            if not isinstance(secrets_list, list):
                return {}
            result = {}
            for secret in secrets_list:
                if not isinstance(secret, dict):
                    continue
                key = str(secret.get("secretKey") or secret.get("key") or "").strip()
                value = str(
                    secret.get("secretValue") or secret.get("value") or ""
                ).strip()
                if key and value:
                    result[key] = value
            return result
    except Exception:
        return {}


def _fetch_infisical_access(
    host: str, client_id: str, client_secret: str
) -> tuple[Optional[bool], str]:
    """
    Validate Infisical Universal Auth credentials.

    Returns:
    - allowed: True/False if request succeeded
    - allowed: None if request failed (network/server)
    - reason: failure reason for logging
    """
    log_info("infisical", f"Validating access: host={host} client_id={client_id[:8]}...")

    project_id, environment, secret_path = _resolve_infisical_scope()
    log_debug(
        "infisical",
        f"Scope: project={project_id} env={environment} path={secret_path}",
    )

    mismatch = _required_project_id_mismatch_reason()
    if mismatch:
        log_error("infisical", f"Access denied: {mismatch}")
        return False, mismatch

    token = _infisical_login(host, client_id, client_secret)
    if not token:
        log_error(
            "infisical",
            "Access denied: auth_failed (could not obtain access token). "
            "Check that Client ID and Secret are correct and the Machine Identity exists.",
        )
        return False, "auth_failed"

    # Enforce project access by listing secrets for the required project.
    from urllib.parse import urlencode

    query = urlencode(
        {
            "projectId": project_id,
            "environment": environment,
            "secretPath": secret_path,
            "expandSecretReferences": "false",
            "includeImports": "false",
            "recursive": "false",
        }
    )
    secrets_url = f"{host}/api/v4/secrets?{query}"
    secrets_req = Request(secrets_url, method="GET")
    secrets_req.add_header("Authorization", f"Bearer {token}")
    secrets_req.add_header("Accept", "application/json")
    secrets_req.add_header("User-Agent", _DEFAULT_USER_AGENT)

    log_debug("infisical", f"GET {secrets_url}")

    try:
        with urlopen(secrets_req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
            _ = resp.read()  # intentionally ignored
            log_info("infisical", "Access validated successfully")
            return True, ""
    except HTTPError as err:
        try:
            body = err.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        reason = f"http_{err.code}"
        log_error(
            "infisical",
            f"Access denied: {reason} ({err.reason}) body={body[:300]}",
        )
        if 400 <= err.code < 500:
            return False, reason
        return None, reason
    except Exception as exc:
        reason = f"request_failed:{exc.__class__.__name__}"
        log_error("infisical", f"Access check failed: {reason} ({exc})")
        return None, reason


def _debug_enabled() -> bool:
    return _env_bool(os.environ.get(INFISICAL_ENV_DEBUG))


def _debug_log(message: str) -> None:
    if _debug_enabled():
        print(f"[infisical] {message}", file=os.sys.stderr)


def _safe_response_excerpt(raw: str, limit: int = 400) -> str:
    if not raw:
        return ""
    text = raw.replace("\n", " ").replace("\r", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…"


def _fetch_json_with_fallback(
    host: str, token: str, paths: list[str]
) -> Optional[dict]:
    """Try multiple API paths and return the first JSON dict response."""
    for path in paths:
        url = f"{host}{path}"
        req = Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/json")
        req.add_header("User-Agent", _DEFAULT_USER_AGENT)
        try:
            with urlopen(req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
                raw = resp.read().decode("utf-8", errors="replace").strip()
                data = json.loads(raw) if raw else {}
                if isinstance(data, dict):
                    _debug_log(f"GET {url} -> {resp.status}")
                    return data
                _debug_log(f"GET {url} -> {resp.status} (non-dict JSON)")
        except HTTPError as err:
            try:
                body = err.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            _debug_log(
                f"GET {url} -> HTTP {err.code} {err.reason} "
                f"body='{_safe_response_excerpt(body)}'"
            )
        except Exception as exc:
            _debug_log(f"GET {url} -> error {exc.__class__.__name__}")
            continue
    _debug_log(f"All fallback endpoints failed for host={host}")
    return None


def _extract_name_from_payload(payload: dict, keys: list[str]) -> Optional[str]:
    """Extract a name from nested payload keys."""
    for key in keys:
        candidate = payload.get(key)
        if isinstance(candidate, dict):
            name = str(candidate.get("name") or "").strip()
            if name:
                return name
    name = str(payload.get("name") or "").strip()
    return name or None


def _extract_org_name_from_workspace_payload(payload: dict) -> Optional[str]:
    """
    Extract org name from a workspace payload.

    We prefer this path because some org endpoints are blocked (Cloudflare 403),
    while the workspace endpoint is accessible with Universal Auth.
    """
    workspace = payload.get("workspace")
    if isinstance(workspace, dict):
        org = workspace.get("organization") or workspace.get("org")
        if isinstance(org, dict):
            name = str(org.get("name") or "").strip()
            if name:
                return name
        # Some versions may flatten org info
        name = str(
            workspace.get("organizationName") or workspace.get("orgName") or ""
        ).strip()
        if name:
            return name

    # Fallback: flattened payload
    org = payload.get("organization") or payload.get("org")
    if isinstance(org, dict):
        name = str(org.get("name") or "").strip()
        if name:
            return name

    name = str(payload.get("organizationName") or payload.get("orgName") or "").strip()
    return name or None


def _fetch_project_name(host: str, token: str, project_id: str) -> Optional[str]:
    """
    Fetch project name from Infisical workspace API.

    Returns:
    - project_name on success
    - None on failure
    """
    payload = _fetch_json_with_fallback(
        host,
        token,
        [
            f"/api/v2/workspace/{project_id}",
            f"/api/v2/workspaces/{project_id}",
            f"/api/v1/workspace/{project_id}",
            f"/api/v1/workspaces/{project_id}",
        ],
    )
    if not payload:
        return None
    return _extract_name_from_payload(payload, ["workspace", "project"])


def _fetch_org_name(host: str, token: str, org_id: str) -> Optional[str]:
    """
    Fetch organization name from Infisical organization API.

    Returns:
    - org_name on success
    - None on failure
    """
    payload = _fetch_json_with_fallback(
        host,
        token,
        [
            f"/api/v2/organization/{org_id}",
            f"/api/v2/organizations/{org_id}",
            f"/api/v1/organization/{org_id}",
            f"/api/v1/organizations/{org_id}",
        ],
    )
    if not payload:
        return None
    return _extract_name_from_payload(payload, ["organization", "org"])


def _fetch_scope_display_names(
    host: str, client_id: str, client_secret: str
) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch human-readable project and org names for display in setup UI.

    Returns:
    - (project_name, org_name) on success
    - (None, None) on failure (will fall back to UUIDs in UI)
    """
    from .config import REQUIRED_INFISICAL_ORG_ID

    token = _infisical_login(host, client_id, client_secret)
    if not token:
        return None, None

    project_id, _, _ = _resolve_infisical_scope()

    # Prefer workspace payload for BOTH project + org names (org endpoints may be blocked).
    workspace_payload = _fetch_json_with_fallback(
        host,
        token,
        [
            f"/api/v1/workspace/{project_id}",
            f"/api/v2/workspace/{project_id}",
            f"/api/v2/workspaces/{project_id}",
            f"/api/v1/workspaces/{project_id}",
        ],
    )
    if workspace_payload:
        project_name = _extract_name_from_payload(
            workspace_payload, ["workspace", "project"]
        )
        org_name = _extract_org_name_from_workspace_payload(workspace_payload)
        if _debug_enabled():
            _debug_log(
                "workspace_extract"
                f" project_name={'set' if project_name else 'missing'}"
                f" org_name={'set' if org_name else 'missing'}"
            )
    else:
        project_name = None
        org_name = None

    # If org name still missing, try explicit org endpoints as a last resort.
    if not org_name:
        org_name = _fetch_org_name(host, token, REQUIRED_INFISICAL_ORG_ID)

    if _debug_enabled():
        _debug_log(
            "display_names"
            f" project_name={'set' if project_name else 'missing'}"
            f" org_name={'set' if org_name else 'missing'}"
        )

    return project_name, org_name


def _fetch_github_oauth_from_infisical(
    host: str, client_id: str, client_secret: str
) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch GitHub OAuth credentials from Infisical.

    Returns:
    - (github_client_id, github_client_secret) on success
    - (None, None) on failure
    """
    token = _infisical_login(host, client_id, client_secret)
    if not token:
        return None, None

    project_id, environment, secret_path = _resolve_infisical_scope()
    secrets = _fetch_infisical_secrets(
        host, token, project_id, environment, secret_path
    )

    github_id = secrets.get("MOOVENT_GITHUB_CLIENT_ID") or secrets.get(
        "GITHUB_CLIENT_ID"
    )
    github_secret = secrets.get("MOOVENT_GITHUB_CLIENT_SECRET") or secrets.get(
        "GITHUB_CLIENT_SECRET"
    )
    return github_id, github_secret


def _ensure_github_oauth_from_infisical() -> None:
    """
    Fetch GitHub OAuth from Infisical if not already in config.
    Called when Step 2 loads to handle users who completed Step 1 before this feature.
    """
    cfg = _load_config()
    # Skip if already have OAuth creds
    if cfg.get("github_client_id") and cfg.get("github_client_secret"):
        return

    # Need Infisical creds to fetch
    infisical_host = str(cfg.get("infisical_host") or "").strip()
    infisical_client_id = str(cfg.get("infisical_client_id") or "").strip()
    infisical_client_secret = str(cfg.get("infisical_client_secret") or "").strip()
    if not (infisical_host and infisical_client_id and infisical_client_secret):
        return

    github_id, github_secret = _fetch_github_oauth_from_infisical(
        infisical_host, infisical_client_id, infisical_client_secret
    )
    if github_id and github_secret:
        _save_config(
            {"github_client_id": github_id, "github_client_secret": github_secret}
        )
