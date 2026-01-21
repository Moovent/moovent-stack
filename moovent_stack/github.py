"""
GitHub OAuth and API helpers for setup.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .config import (
    ACCESS_REQUEST_TIMEOUT_S,
    DEFAULT_GITHUB_SCOPES,
    GITHUB_ENV_ACCESS_TOKEN,
    GITHUB_ENV_CLIENT_ID,
    GITHUB_ENV_CLIENT_SECRET,
    __version__,
)
from .storage import _load_config


def _resolve_github_oauth_settings() -> tuple[Optional[str], Optional[str]]:
    """
    Resolve GitHub OAuth app credentials.

    Priority:
    - environment variables
    - saved config file (~/.moovent_stack_config.json)
    """
    env_client_id = os.environ.get(GITHUB_ENV_CLIENT_ID, "").strip()
    env_client_secret = os.environ.get(GITHUB_ENV_CLIENT_SECRET, "").strip()
    if env_client_id and env_client_secret:
        return env_client_id, env_client_secret

    cfg = _load_config()
    client_id = str(cfg.get("github_client_id") or "").strip()
    client_secret = str(cfg.get("github_client_secret") or "").strip()
    return (client_id or None), (client_secret or None)


def _resolve_github_token() -> Optional[str]:
    """Resolve stored GitHub access token."""
    env_token = os.environ.get(GITHUB_ENV_ACCESS_TOKEN, "").strip()
    if env_token:
        return env_token
    cfg = _load_config()
    token = str(cfg.get("github_access_token") or "").strip()
    return token or None


def _github_user_agent() -> str:
    """Return User-Agent string for GitHub API requests."""
    return f"moovent-stack/{__version__}"


def _split_scopes(value: str) -> set[str]:
    """Split OAuth scope header values into a normalized set."""
    return {scope.strip() for scope in value.split(",") if scope.strip()}


def _read_github_error_message(err: HTTPError) -> str:
    """Extract a useful error message from a GitHub HTTPError response."""
    try:
        raw = err.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return ""
    if not raw:
        return ""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return str(data.get("message") or "").strip()
    except Exception:
        pass
    return raw


def _describe_github_http_error(err: HTTPError) -> tuple[str, bool]:
    """
    Return a user-facing error message and whether to reconnect.

    - Reconnect when token is invalid/expired or missing required scopes.
    - Keep token for org access/SSO errors so user can authorize it.
    """
    message = _read_github_error_message(err)
    message_lower = message.lower()
    token_scopes = str(err.headers.get("X-OAuth-Scopes") or "").strip()
    accepted_scopes = str(err.headers.get("X-Accepted-OAuth-Scopes") or "").strip()

    if err.code == 401:
        return "GitHub token expired or invalid. Please reconnect.", True

    if "sso" in message_lower:
        return (
            "GitHub SSO authorization required for Moovent. "
            "Open https://github.com/orgs/Moovent/sso and authorize the OAuth app, then retry.",
            False,
        )

    if token_scopes and accepted_scopes:
        token_scope_set = _split_scopes(token_scopes)
        accepted_scope_set = _split_scopes(accepted_scopes)
        missing_scopes = sorted(accepted_scope_set - token_scope_set)
        if missing_scopes:
            return (
                "GitHub token missing required scopes "
                f"({', '.join(missing_scopes)}). Please reconnect and approve permissions.",
                True,
            )

    if err.code == 403:
        return (
            "GitHub access forbidden. Check org access or authorize SSO, then retry.",
            False,
        )

    if err.code == 404:
        return (
            "GitHub repo not found or access denied. Check your org membership.",
            False,
        )

    fallback = message or err.reason or "Unknown GitHub API error"
    return f"GitHub API error {err.code}: {fallback}", False


def _github_api_request(url: str, token: str) -> dict:
    """Call GitHub API with token and return JSON dict."""
    req = Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", _github_user_agent())
    with urlopen(req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
        raw = resp.read().decode("utf-8").strip()
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            raise ValueError("invalid_response")
        return data


def _github_exchange_code(client_id: str, client_secret: str, code: str) -> str:
    """Exchange OAuth code for an access token."""
    url = "https://github.com/login/oauth/access_token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, method="POST")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    with urlopen(req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
        raw = resp.read().decode("utf-8").strip()
        data = json.loads(raw) if raw else {}
        token = str(data.get("access_token") or "").strip()
        if not token:
            raise ValueError("missing_access_token")
        return token


def _github_get_login(token: str) -> Optional[str]:
    """Fetch GitHub login for the token."""
    try:
        data = _github_api_request("https://api.github.com/user", token)
        return str(data.get("login") or "").strip() or None
    except Exception:
        return None


def _github_list_branches(
    owner: str, repo: str, token: str
) -> tuple[list[str], str, bool]:
    """
    List branch names for a repo.

    Returns:
    - branches: list of branch names
    - error_text: user-facing error string (empty if no error)
    - should_reconnect: whether OAuth reconnect is required
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100"
    req = Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", _github_user_agent())
    try:
        with urlopen(req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8").strip()
            data = json.loads(raw) if raw else []
            if not isinstance(data, list):
                return (
                    [],
                    f"GitHub API returned unexpected response for {owner}/{repo}.",
                    False,
                )
            branches = [
                str(item.get("name") or "").strip()
                for item in data
                if isinstance(item, dict)
            ]
            return branches, "", False
    except HTTPError as err:
        error_text, should_reconnect = _describe_github_http_error(err)
        print(f"[setup] GitHub API error {err.code}: {error_text}", file=sys.stderr)
        return [], f"{owner}/{repo}: {error_text}", should_reconnect
    except Exception as exc:
        print(f"[setup] GitHub API error: {exc}", file=sys.stderr)
        return [], f"{owner}/{repo}: GitHub API request failed. Please retry.", False


__all__ = [
    "DEFAULT_GITHUB_SCOPES",
    "_resolve_github_oauth_settings",
    "_resolve_github_token",
    "_github_exchange_code",
    "_github_get_login",
    "_github_list_branches",
]
