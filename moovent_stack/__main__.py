#!/usr/bin/env python3
"""
moovent-stack: internal dev launcher (local-only).

Security model:
- Runs local stack from a user-provided workspace (`run_local_stack.py`).
- This CLI enforces an internal access check before doing anything.
- On revoke, it can optionally self-clean its Homebrew install on next run.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs
from urllib.error import HTTPError
from urllib.request import Request, urlopen


# ----------------------------
# Config / environment knobs
# ----------------------------
INFISICAL_ENV_HOST = "INFISICAL_HOST"
INFISICAL_ENV_CLIENT_ID = "INFISICAL_CLIENT_ID"
INFISICAL_ENV_CLIENT_SECRET = "INFISICAL_CLIENT_SECRET"
INFISICAL_ENV_PROJECT_ID = "INFISICAL_PROJECT_ID"
INFISICAL_ENV_ENVIRONMENT = "INFISICAL_ENVIRONMENT"
INFISICAL_ENV_SECRET_PATH = "INFISICAL_SECRET_PATH"
GITHUB_ENV_CLIENT_ID = "MOOVENT_GITHUB_CLIENT_ID"
GITHUB_ENV_CLIENT_SECRET = "MOOVENT_GITHUB_CLIENT_SECRET"
GITHUB_ENV_ACCESS_TOKEN = "MOOVENT_GITHUB_ACCESS_TOKEN"
ACCESS_ENV_TTL = "MOOVENT_ACCESS_TTL_S"
ACCESS_ENV_SELF_CLEAN = "MOOVENT_ACCESS_SELF_CLEAN"
ACCESS_ENV_INSTALL_ROOT = "MOOVENT_INSTALL_ROOT"
ACCESS_ENV_CACHE_PATH = "MOOVENT_ACCESS_CACHE_PATH"
WORKSPACE_ENV_ROOT = "MOOVENT_WORKSPACE_ROOT"
RUNNER_ENV_PATH = "MOOVENT_RUNNER_PATH"

SETUP_ENV_NONINTERACTIVE = "MOOVENT_SETUP_NONINTERACTIVE"
SETUP_ENV_PORT = "MOOVENT_SETUP_PORT"

DEFAULT_ACCESS_TTL_S = 24 * 60 * 60
ACCESS_REQUEST_TIMEOUT_S = 5.0
DEFAULT_SETUP_PORT = 9010

DEFAULT_CACHE_PATH = Path.home() / ".moovent_stack_access.json"
CONFIG_PATH = Path.home() / ".moovent_stack_config.json"
DEFAULT_INFISICAL_HOST = "https://app.infisical.com"
DEFAULT_GITHUB_SCOPES = "repo read:org"

#
# Infisical scope (org/project) enforcement
#
# Purpose:
# - Prevent users from proceeding past setup unless their Universal Auth creds can
#   access the *required* Infisical project (and therefore the correct org).
#
# Notes:
# - Today we have a single org + single project. We enforce those IDs here.
# - We validate access by listing secrets scoped to the required project ID.
# - This mirrors the mqtt_dashboard_watch integration (Universal Auth + list_secrets).
REQUIRED_INFISICAL_ORG_ID = "20256abe-9337-498a-af56-d08d6e762d29"
REQUIRED_INFISICAL_PROJECT_ID = "b33db90d-cc5b-464e-b58c-a09e7328e83d"
DEFAULT_INFISICAL_ENVIRONMENT = "dev"
DEFAULT_INFISICAL_SECRET_PATH = "/"


def _env_bool(value: Optional[str]) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_bool_default(value: Optional[str], default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return _env_bool(value)


def _cache_path() -> Path:
    raw = os.environ.get(ACCESS_ENV_CACHE_PATH, "").strip()
    return Path(raw) if raw else DEFAULT_CACHE_PATH


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        # Best-effort: make file user-readable only (important for tokens).
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception:
        return


def _load_config() -> dict:
    """Load setup config (access URL/token) from disk."""
    return _load_json(CONFIG_PATH)


def _save_config(data: dict) -> None:
    """Persist setup config to disk."""
    current = _load_config()
    current.update(data)
    _save_json(CONFIG_PATH, current)


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
    host = _normalize_infisical_host(str(cfg.get("infisical_host") or "").strip() or host)
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


def _setup_noninteractive() -> bool:
    """When true, do not open the setup page; fail fast instead."""
    return _env_bool(os.environ.get(SETUP_ENV_NONINTERACTIVE))


def _setup_port() -> int:
    """Local setup server port (default 9010)."""
    raw = os.environ.get(SETUP_ENV_PORT, "").strip()
    if not raw:
        return DEFAULT_SETUP_PORT
    try:
        value = int(raw)
        return value if value > 0 else DEFAULT_SETUP_PORT
    except ValueError:
        return DEFAULT_SETUP_PORT


def _resolve_runner_path() -> Optional[Path]:
    """Resolve the path to run_local_stack.py."""
    raw_runner = os.environ.get(RUNNER_ENV_PATH, "").strip()
    if raw_runner:
        return Path(raw_runner).expanduser()

    raw_root = os.environ.get(WORKSPACE_ENV_ROOT, "").strip()
    if raw_root:
        return (Path(raw_root).expanduser() / "run_local_stack.py")

    cfg = _load_config()
    root = str(cfg.get("workspace_root") or "").strip()
    if root:
        return (Path(root).expanduser() / "run_local_stack.py")

    return None


def _validate_runner_path(path: Path) -> tuple[bool, str]:
    """Validate workspace layout for local stack."""
    if not path.exists():
        return False, f"run_local_stack.py not found at: {path}"
    root = path.parent
    missing = []
    if not (root / "mqtt_dashboard_watch").exists():
        missing.append("mqtt_dashboard_watch/")
    if not (root / "dashboard").exists():
        missing.append("dashboard/")
    if missing:
        return False, f"Workspace missing: {', '.join(missing)} (expected under {root})"
    return True, ""


# ---------------------------------------------------------------------------
# HTML Templates for setup UI
# ---------------------------------------------------------------------------

# Moovent brand colors (matching mqtt-admin-dashboard tailwind.config.js)
_MOOVENT_BLUE = "#A2CCF2"
_MOOVENT_TEAL = "#A6D8D4"
_MOOVENT_GREEN = "#A8DFB4"
_MOOVENT_ACCENT = "#3A8FD2"
_MOOVENT_BACKGROUND = "#FAFBFC"  # brand-background from dashboard

# Moovent logo PNG as base64 (from mqtt-admin-dashboard/public/moovent-logo.png)
# This embeds the logo directly so the setup page works offline without external deps
_MOOVENT_LOGO_BASE64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAABdwAAAGoCAYAAABcySegAAAAAXNSR0IArs4c6QAAAIRlWElmTU0AKgAAAAgABQESAAMAAAABAAEAAAEaAAUAAAABAAAASgEbAAUAAAABAAAAUgEoAAMAAAABAAIAAIdpAAQAAAABAAAAWgAAAAAAAAEsAAAAAQAAASwAAAABAAOgAQADAAAAAQABAACgAgAEAAAAAQAABdygAwAEAAAAAQAAAagAAAAA3E9bAAAAAAlwSFlzAAAuIwAALiMBeKU/dgAAAVlpVFh0WE1MOmNvbS5hZG9iZS54bXAAAAAAADx4OnhtcG1ldGEgeG1sbnM6eD0iYWRvYmU6bnM6bWV0YS8iIHg6eG1wdGs9IlhNUCBDb3JlIDYuMC4wIj4KICAgPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4KICAgICAgPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIKICAgICAgICAgICAgeG1sbnM6dGlmZj0iaHR0cDovL25zLmFkb2JlLmNvbS90aWZmLzEuMC8iPgogICAgICAgICA8dGlmZjpPcmllbnRhdGlvbj4xPC90aWZmOk9yaWVudGF0aW9uPgogICAgICA8L3JkZjpEZXNjcmlwdGlvbj4KICAgPC9yZGY6UkRGPgo8L3g6eG1wbWV0YT4KGV7hBwAAQABJREFUeAHsnQeAHkd99ufae70XnaST7iSdekOWO7aRKxibjugkBBJDIB8kgRDqF9ETkpCEDwIkhtCLRQnVuGG5Icu2LDfJsupJOrXrvZfveWZ33tu3XZFO0pVnpP9tm52d+U3Z3WfmnTVGTgREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQARmKIGkGZouJUsEREAEREAEREAEREAEREAEREAEREAEREAEREAEpioB6rIzTZsdRppos9rNtEyd1ZmpxIuACIiACIiACIiACIiACIiACIiACIiACIiACEwLAjNRl531Yvu0KHmKpAiIgAiIgAiIgAiIgAiIgAiIgAiIgAiIgAiIgAiIwLQgMBM7EiYEftYDmBAteRYBERABERABERABERABERABERABERABERABERCBMyXAX3iwAyrV74SiuJ5Q7N64aVMJOqxKUL7ntzc0lKRlZy9oqa/Pz83PL+/t7i7qaG3NzCspKR4eHMztausI9XZ1JIWystLTMzMzUUX8OsLHumGDKpI0ODg40NXS0pkSCg1l5eYOpmdkdsM19vd0txeWlXV1dXQcD6Wnt2RmZ5/u6e09WVRYWDc0NHRyw/LljVu3bk30YEwRPs1UVCStzs8f3L17N+tI3HqP/XIiIAIiIAIiIAIiIAIiIAIiIAIiIAIiIAIiIAKxBJwWy2d4Ce6xfGbEHpfJMyIxSoQIiIAIiIAIiIAIiIAIiIAIiIAIiIAIiIAIiMA5I5CEEeypp0+fTq31BPZeXCkshPOqW7ZsSd56768rOltaF/f19FT39vQvGR4aXNzfO1ABIW/uwEB/EUaq5w/2Q6NLSjIDvf0Gg9XN0BCCcXrhWUYfwrsNAXqjSQmlmeGhIZMaSuvBdlNKKLU+OSn5eFoo7WhKcsr+1KyMA1kZmQcrlpUd2bZ1W0ucS1OAT8Xo3sEDbzvQj6loJCzGgaRdAQIYwV69a1fqgQMHKExTjI4R2C+7+ea85lOnFrW3tS0e6O1dNjg8iPrSV4mSOw/1pjQ5JaWor7s7lJKaavp7Wc08x7I8GY51g/WPdS4lLc0kJdup3IfRUdWKXY2podBJ1JNaLA+mpacdDKVm7i8szjv89Pbtx+NcnyenV1RUmDlz5gxgBPy4RuvHCUe7REAEREAEREAEREAERGC2EPBeWr33aQnuMzTXXSbP0OQpWSIgAiIgAiIgAiIgAiIgAiIgAiIgAiIgAiIgAudBIAlic8gXDymkRYhpm169qaD26OkVna1t6/u6+9b29fevGhwYXDTY318+2D+YQYFwaGAoOEA9GBWqh86ccO+W1h/Ec96jaG6/W0+yI3qHw/utf/8P/VAEpOAZd/5rivzWUlOGIGrWp6alHoMovy+UnvZcWih0VEF52XPPPfj4MT88t2C4GRQWr7jiij6MANb0M47MLF/yOwWoI2noiCKJmJHhyy65ZHF3W/Pa7q7edYP9fWv7+weqUUcWDPT1lQwNDhraKGI6y5mrJwzf1QWuUzi3ztuwx8J1hBXP1hP/YGBBP8F6wvUIRxGelpKSapJT0zpT0lJPpqWlHUoLpe9JSU9/Nic78+klc1+09+67v9cZcaI3Hzy/2zCA0e9sLyLjG+VZmyIgAiIgAiIgAiIgAiIwCwm4528+K0twn6EFwGXyDE2ekiUCIiACIiACIiACIiACIiACIiACIiACIiACBywBv2w/QgROlQ6pSJys62skXrDzzXbkP4p+tcJYXraPOeQYAiEwJYEsHlMCS/IQCIEQCIEQCIEQCIEQCIEQCIEQCIEQCIF9msBBat1uaa30Q+kp6Q6Jb7evlNZJh0k24nn5jl02PuUYAiEQAiEQAiEQAiEQAiEQAiEQAiEQAiEQAiEQAiEQAiHgP4h6oVD4Z2Lqc/kzMrsm6b41QZcvqMaHQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQkAE+COp2AaJF+38XMx/JmFetBPm/G/pGYk0d0r+6Rn/JI2iYiEQAiEwHYH8i910vJI6BEIgBEIgBEIgBEIgBEIgBEIgBEIgBEJg3yXAy3JeqGP+46fl77Tz8zGk4cyLeXSrdIH0rMQfV+VlfCwEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAEDmgC5bfTLxYJf4O9/kkZru+SPiP5C6llXkXHQiAEQmB6AvxrXiwEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAE9hcC5R9BPVydWiO9QjpY4t4/pK3SvRI/N4Pxsp1vwsdCIARCIARCIARCIARCIARCIARCIARCIARCIARCIARCIARmJJAvpM4ILtlCIAQWE8iCsphJYkIgBEIgBEIgBEIgBEIgBEIgBEIgBEIgBJY/gfK9VxmmZ/ykjK0MOy7nEAiBEJiJwP8Ap5WLjkKLfL4AAAAASUVORK5CYII="


def _setup_steps_html(current_step: int) -> str:
    """Render the step list group (from help/tailwind set-up flows)."""
    steps = [
        "Infisical credentials",
        "GitHub + install path",
        "Repo + branch selection",
    ]
    items = []
    for idx, label in enumerate(steps, start=1):
        if idx < current_step:
            icon = (
                '<span class="size-5 flex shrink-0 justify-center items-center '
                'bg-teal-600 text-white rounded-full">'
                '<svg class="shrink-0 size-3.5" xmlns="http://www.w3.org/2000/svg" '
                'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                'stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"></path></svg>'
                "</span>"
            )
            text = f'<s class="text-sm text-gray-400">{label}</s>'
        elif idx == current_step:
            icon = (
                '<span class="size-5 flex shrink-0 justify-center items-center '
                'border border-dashed border-gray-300 text-gray-500 rounded-full">'
                f'<span class="text-[11px]">{idx}</span></span>'
            )
            text = f'<span class="text-sm text-gray-800 font-medium">{label}</span>'
        else:
            icon = (
                '<span class="size-5 flex shrink-0 justify-center items-center '
                'border border-dashed border-gray-300 text-gray-500 rounded-full">'
                f'<span class="text-[11px]">{idx}</span></span>'
            )
            text = f'<span class="text-sm text-gray-600">{label}</span>'
        items.append(
            f"""
            <div class="py-2 px-2.5 flex items-center gap-x-3 bg-gray-100 rounded-lg">
              {icon}
              <div class="grow">{text}</div>
            </div>
            """
        )
    return f'<div class="space-y-1.5">{"".join(items)}</div>'


def _setup_shell(
    step_title: str,
    step_subtitle: str,
    step_index: int,
    step_total: int,
    content_html: str,
    error_text: str = "",
) -> str:
    """Render the shared setup shell."""
    error_block = ""
    if error_text:
        error_block = f"""
        <div class="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error_text}
        </div>
        """

    progress_cells = []
    for i in range(1, step_total + 1):
        bar_class = "bg-teal-600" if i <= step_index else "bg-teal-600 opacity-30"
        progress_cells.append(f'<div class="{bar_class} h-2 flex-auto rounded-sm"></div>')

    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Moovent Stack Setup</title>
    <link rel="icon" href="{_MOOVENT_LOGO_BASE64}" />
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="text-gray-800" style="background-color: {_MOOVENT_BACKGROUND};">
    <main class="min-h-screen flex items-center justify-center px-4 py-10">
      <div class="w-full max-w-xl">
        <div class="mb-6 text-center">
          <div class="mx-auto flex items-center justify-center">
            <img src="{_MOOVENT_LOGO_BASE64}" alt="Moovent" class="h-16" />
          </div>
          <h1 class="mt-4 font-semibold text-2xl text-gray-800">Welcome to Moovent Stack</h1>
          <p class="mt-2 text-sm text-gray-500">
            Run the full Moovent development environment locally.<br/>
            Quick setup, then you're ready to code.
          </p>
        </div>

        <div class="relative overflow-hidden bg-white border border-gray-200 rounded-xl shadow-sm">
          <div class="p-5" style="background: linear-gradient(to right, {_MOOVENT_BLUE}40, {_MOOVENT_TEAL}40, {_MOOVENT_GREEN}40);">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 class="font-semibold text-gray-800">{step_title}</h2>
                <p class="mt-1 text-xs text-gray-600">{step_subtitle}</p>
              </div>
              <span class="py-1 px-2 inline-flex items-center gap-x-1 text-xs font-semibold uppercase rounded-md text-white"
                style="background: linear-gradient(to top right, {_MOOVENT_ACCENT}, #14b8a6);">
                Setup
              </span>
            </div>

            <div class="mt-4">
              <div class="flex items-center justify-between">
                <span class="text-xs text-gray-600">Step {step_index} of {step_total}</span>
                <span class="text-xs text-gray-600">{step_title}</span>
              </div>
              <div class="mt-2 grid grid-cols-{step_total} gap-x-1.5">
                {''.join(progress_cells)}
              </div>
            </div>
          </div>

          <div class="p-5 space-y-5">
            {error_block}
            {content_html}
          </div>
        </div>

        <div class="mt-4 p-4 bg-white border border-gray-200 rounded-xl">
          <h3 class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">Setup steps</h3>
          {_setup_steps_html(step_index)}
        </div>

        <p class="mt-6 text-center text-xs text-gray-500">
          Need help? Contact your team lead or check the
          <a href="https://github.com/Moovent/mqtt_dashboard_watch/blob/main/help/INSTALLATION.md" target="_blank"
            class="hover:underline" style="color: {_MOOVENT_ACCENT};">installation guide</a>.
        </p>
      </div>
    </main>
  </body>
</html>
""".strip()


def _setup_step1_html(error_text: str = "") -> str:
    """Step 1: Infisical credentials only."""
    content = f"""
    <form class="space-y-5" method="POST" action="/save-step1">
      <div>
        <label class="block mb-2 text-sm font-medium text-gray-800">
          Infisical Client ID <span class="text-red-500">*</span>
        </label>
        <input
          name="client_id"
          required
          autocomplete="username"
          placeholder="infisical_client_id_xxx"
          class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50 focus:border-[{_MOOVENT_ACCENT}]"
        />
      </div>

      <div>
        <label class="block mb-2 text-sm font-medium text-gray-800">
          Infisical Client Secret <span class="text-red-500">*</span>
        </label>
        <input
          name="client_secret"
          type="password"
          required
          autocomplete="current-password"
          placeholder="infisical_client_secret_xxx"
          class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50 focus:border-[{_MOOVENT_ACCENT}]"
        />
        <p class="mt-2 text-xs text-gray-500">
          Stored locally with restricted permissions. Default host: app.infisical.com (set INFISICAL_HOST to override).
        </p>
      </div>

      <div class="p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <p class="text-xs text-gray-500 mb-1">Access scope</p>
        <p class="text-sm text-gray-800">
          Org: <span class="font-mono text-xs">{REQUIRED_INFISICAL_ORG_ID}</span><br/>
          Project: <span class="font-mono text-xs">{REQUIRED_INFISICAL_PROJECT_ID}</span><br/>
          Env: <span class="font-mono text-xs">{DEFAULT_INFISICAL_ENVIRONMENT}</span>
        </p>
        <p class="mt-2 text-xs text-gray-500">
          We verify your credentials can access this project before continuing.
        </p>
      </div>

      <div class="pt-2">
        <button
          type="submit"
          class="py-3 px-4 w-full inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-transparent text-white hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2"
          style="background-color: {_MOOVENT_ACCENT}; --tw-ring-color: {_MOOVENT_ACCENT};"
        >
          Continue
          <svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M12 5l7 7-7 7"/></svg>
        </button>
      </div>
    </form>
    """
    return _setup_shell(
        "Infisical access",
        "Sign in with your Infisical Universal Auth credentials",
        1,
        3,
        content,
        error_text,
    )


def _setup_step2_html(
    github_login: Optional[str],
    error_text: str = "",
    workspace_root: str = "",
    oauth_ready: bool = True,
) -> str:
    """Step 2: GitHub OAuth + install path."""
    status = (
        f'<span class="inline-flex items-center gap-2 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-1 rounded-md">Connected as {github_login}</span>'
        if github_login
        else '<span class="text-xs text-gray-500">Not connected yet</span>'
    )
    oauth_hint = "" if oauth_ready else "<p class='text-xs text-red-600 mt-2'>Missing GitHub OAuth Client ID/Secret.</p>"

    content = f"""
    <form class="space-y-5" method="POST" action="/save-step2">
      <div>
        <label class="block mb-2 text-sm font-medium text-gray-800">
          Workspace Install Path <span class="text-red-500">*</span>
        </label>
        <input
          name="workspace_root"
          required
          autocomplete="off"
          placeholder="/Users/you/Projects/moovent"
          value="{workspace_root}"
          class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50 focus:border-[{_MOOVENT_ACCENT}]"
        />
        <p class="mt-2 text-xs text-gray-500">This is where repos will be installed.</p>
      </div>

      <div class="p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <div class="flex items-center justify-between gap-3">
          <div>
            <p class="text-sm font-medium text-gray-800">Connect GitHub</p>
            <p class="text-xs text-gray-500">Authorize Moovent Stack to access your repos.</p>
          </div>
          <a href="/oauth/start" class="py-2 px-3 inline-flex items-center gap-x-2 text-xs font-medium rounded-lg border border-gray-200 bg-white text-gray-800 hover:bg-gray-50">
            Connect
          </a>
        </div>
        <div class="mt-2">{status}</div>
        {oauth_hint}
      </div>

      <div class="p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <p class="text-xs text-gray-500 mb-2">Admin settings (OAuth App)</p>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <input name="github_client_id" placeholder="GitHub OAuth Client ID"
            class="py-2.5 px-3 block w-full bg-white border border-gray-200 rounded-lg text-xs text-gray-800 placeholder:text-gray-400" />
          <input name="github_client_secret" placeholder="GitHub OAuth Client Secret"
            class="py-2.5 px-3 block w-full bg-white border border-gray-200 rounded-lg text-xs text-gray-800 placeholder:text-gray-400" />
        </div>
      </div>

      <div class="pt-2">
        <button
          type="submit"
          class="py-3 px-4 w-full inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-transparent text-white hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2"
          style="background-color: {_MOOVENT_ACCENT}; --tw-ring-color: {_MOOVENT_ACCENT};"
        >
          Continue
          <svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M12 5l7 7-7 7"/></svg>
        </button>
      </div>
    </form>
    """
    return _setup_shell(
        "GitHub + install path",
        "Authorize GitHub and choose where repos will be installed",
        2,
        3,
        content,
        error_text,
    )


def _setup_step3_html(
    mqtt_branches: list[str],
    dashboard_branches: list[str],
    error_text: str = "",
) -> str:
    """Step 3: Repo + branch selection."""
    mqtt_options = "\n".join([f"<option value='{b}'></option>" for b in mqtt_branches])
    dash_options = "\n".join([f"<option value='{b}'></option>" for b in dashboard_branches])
    content = f"""
    <form class="space-y-5" method="POST" action="/save-step3">
      <div>
        <label class="block mb-2 text-sm font-medium text-gray-800">
          mqtt_dashboard_watch branch
        </label>
        <input name="mqtt_branch" list="mqtt-branches" placeholder="main"
          class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50 focus:border-[{_MOOVENT_ACCENT}]" />
        <datalist id="mqtt-branches">{mqtt_options}</datalist>
      </div>

      <div>
        <label class="block mb-2 text-sm font-medium text-gray-800">
          dashboard branch
        </label>
        <input name="dashboard_branch" list="dashboard-branches" placeholder="main"
          class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50 focus:border-[{_MOOVENT_ACCENT}]" />
        <datalist id="dashboard-branches">{dash_options}</datalist>
      </div>

      <div class="pt-2">
        <button
          type="submit"
          class="py-3 px-4 w-full inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-transparent text-white hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2"
          style="background-color: {_MOOVENT_ACCENT}; --tw-ring-color: {_MOOVENT_ACCENT};"
        >
          Download &amp; Configure
          <svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M12 5l7 7-7 7"/></svg>
        </button>
      </div>
    </form>
    """
    return _setup_shell(
        "Repo + branches",
        "Select which branches to download",
        3,
        3,
        content,
        error_text,
    )


def _success_page_html() -> str:
    """Render the success page after saving config (light mode only)."""
    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Ready - Moovent Stack</title>
    <link rel="icon" href="{_MOOVENT_LOGO_BASE64}" />
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="text-gray-800" style="background-color: {_MOOVENT_BACKGROUND};">
    <main class="min-h-screen flex items-center justify-center px-4 py-10">
      <div class="w-full max-w-md bg-white border border-gray-200 rounded-xl shadow-sm p-6">
        <div class="mx-auto flex items-center justify-center mb-4">
          <img src="{_MOOVENT_LOGO_BASE64}" alt="Moovent" class="h-12" />
        </div>
        <div class="mx-auto w-14 h-14 flex items-center justify-center rounded-full border-2 border-emerald-500 text-emerald-500">
          <svg class="w-7 h-7" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M20 6L9 17l-5-5"/></svg>
        </div>
        <h2 class="mt-4 text-center font-semibold text-lg text-gray-800">You're all set!</h2>
        <p class="mt-2 text-center text-sm text-gray-500">
          Moovent Stack is starting. You can close this tab.
        </p>
        <div class="mt-5 flex justify-center">
          <button type="button" onclick="window.close()" class="py-2.5 px-4 inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-gray-200 bg-white text-gray-800 shadow-sm hover:bg-gray-50 focus:outline-none focus:bg-gray-50">
            Close tab
          </button>
        </div>
      </div>
    </main>
    <script>setTimeout(() => window.close(), 800);</script>
  </body>
</html>
""".strip()


def _run_setup_server() -> None:
    """
    Launch a local setup page to collect credentials + install settings.
    """

    class _SetupState:
        done: bool = False
        oauth_state: Optional[str] = None
        base_url: Optional[str] = None

    state = _SetupState()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def _send(self, code: int, body: str, content_type: str = "text/html") -> None:
            raw = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _next_step(self) -> int:
            cfg = _load_config()
            if not str(cfg.get("infisical_client_id") or "").strip() or not str(
                cfg.get("infisical_client_secret") or ""
            ).strip():
                return 1
            if not str(cfg.get("workspace_root") or "").strip():
                return 2
            if not str(cfg.get("github_access_token") or "").strip():
                return 2
            return 3

        def do_GET(self) -> None:
            cfg = _load_config()
            if self.path == "/" or self.path.startswith("/?"):
                step = self._next_step()
                if step == 1:
                    self._send(200, _setup_step1_html())
                    return
                if step == 2:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    oauth_ready = all(_resolve_github_oauth_settings())
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                            oauth_ready=oauth_ready,
                        ),
                    )
                    return
                token = _resolve_github_token() or ""
                mqtt_branches = _github_list_branches("Moovent", "mqtt_dashboard_watch", token) if token else []
                dash_branches = _github_list_branches("Moovent", "dashboard", token) if token else []
                self._send(200, _setup_step3_html(mqtt_branches, dash_branches))
                return

            if self.path.startswith("/oauth/start"):
                client_id, client_secret = _resolve_github_oauth_settings()
                if not client_id or not client_secret:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="GitHub OAuth Client ID/Secret is required.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                            oauth_ready=False,
                        ),
                    )
                    return
                state.oauth_state = secrets.token_urlsafe(16)
                redirect_uri = f"{state.base_url}/oauth/callback"
                auth_url = (
                    "https://github.com/login/oauth/authorize"
                    f"?client_id={client_id}"
                    f"&redirect_uri={redirect_uri}"
                    f"&scope={DEFAULT_GITHUB_SCOPES.replace(' ', '%20')}"
                    f"&state={state.oauth_state}"
                )
                self.send_response(302)
                self.send_header("Location", auth_url)
                self.end_headers()
                return

            if self.path.startswith("/oauth/callback"):
                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = parse_qs(query)
                code = (params.get("code", [""])[0] or "").strip()
                returned_state = (params.get("state", [""])[0] or "").strip()
                if not code or not returned_state or returned_state != state.oauth_state:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="GitHub OAuth failed. Please try again.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        ),
                    )
                    return
                client_id, client_secret = _resolve_github_oauth_settings()
                if not client_id or not client_secret:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="GitHub OAuth Client ID/Secret is required.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                            oauth_ready=False,
                        ),
                    )
                    return
                try:
                    token = _github_exchange_code(client_id, client_secret, code)
                    login = _github_get_login(token) or "GitHub user"
                    _save_config({"github_access_token": token, "github_login": login})
                    self.send_response(302)
                    self.send_header("Location", "/step2")
                    self.end_headers()
                    return
                except Exception:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="GitHub OAuth exchange failed. Please try again.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        ),
                    )
                    return

            if self.path.startswith("/step1"):
                self._send(200, _setup_step1_html())
                return

            if self.path.startswith("/step2"):
                github_login = str(cfg.get("github_login") or "").strip() or None
                oauth_ready = all(_resolve_github_oauth_settings())
                self._send(
                    200,
                    _setup_step2_html(
                        github_login,
                        workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        oauth_ready=oauth_ready,
                    ),
                )
                return

            if self.path.startswith("/step3"):
                token = _resolve_github_token() or ""
                if not token:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="Connect GitHub before selecting branches.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        ),
                    )
                    return
                mqtt_branches = _github_list_branches("Moovent", "mqtt_dashboard_watch", token)
                dash_branches = _github_list_branches("Moovent", "dashboard", token)
                self._send(200, _setup_step3_html(mqtt_branches, dash_branches))
                return

            self._send(404, "Not found", "text/plain")

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            form = parse_qs(raw)

            if self.path == "/save-step1":
                client_id = (form.get("client_id", [""])[0] or "").strip()
                client_secret = (form.get("client_secret", [""])[0] or "").strip()
                if not client_id:
                    self._send(200, _setup_step1_html("Infisical Client ID is required."))
                    return
                if not client_secret:
                    self._send(200, _setup_step1_html("Infisical Client Secret is required."))
                    return

                host, _, _ = _resolve_infisical_settings()
                allowed, reason = _fetch_infisical_access(host, client_id, client_secret)
                if not allowed:
                    self._send(
                        200,
                        _setup_step1_html(
                            "Infisical access check failed. "
                            f"Reason: {reason}. "
                            "Ensure your Machine Identity has access to the required project."
                        ),
                    )
                    return

                _save_config(
                    {
                        "infisical_client_id": client_id,
                        "infisical_client_secret": client_secret,
                        "infisical_host": host,
                        # Persist enforced scope so other steps can reuse it.
                        "infisical_org_id": REQUIRED_INFISICAL_ORG_ID,
                        "infisical_project_id": REQUIRED_INFISICAL_PROJECT_ID,
                        "infisical_environment": DEFAULT_INFISICAL_ENVIRONMENT,
                        "infisical_secret_path": DEFAULT_INFISICAL_SECRET_PATH,
                    }
                )
                self.send_response(302)
                self.send_header("Location", "/step2")
                self.end_headers()
                return

            if self.path == "/save-step2":
                workspace_root = (form.get("workspace_root", [""])[0] or "").strip()
                github_client_id = (form.get("github_client_id", [""])[0] or "").strip()
                github_client_secret = (form.get("github_client_secret", [""])[0] or "").strip()
                if not workspace_root:
                    github_login = str(_load_config().get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="Workspace path is required.",
                            workspace_root="",
                        ),
                    )
                    return

                data = {"workspace_root": str(Path(workspace_root).expanduser())}
                if github_client_id:
                    data["github_client_id"] = github_client_id
                if github_client_secret:
                    data["github_client_secret"] = github_client_secret
                _save_config(data)

                self.send_response(302)
                self.send_header("Location", "/step3")
                self.end_headers()
                return

            if self.path == "/save-step3":
                token = _resolve_github_token()
                if not token:
                    self._send(200, _setup_step2_html(None, error_text="Connect GitHub first."))
                    return

                mqtt_branch = (form.get("mqtt_branch", ["main"])[0] or "main").strip()
                dashboard_branch = (form.get("dashboard_branch", ["main"])[0] or "main").strip()
                cfg = _load_config()
                workspace_root = str(cfg.get("workspace_root") or "").strip()
                if not workspace_root:
                    self._send(200, _setup_step2_html(None, error_text="Workspace path is required."))
                    return

                try:
                    root = Path(workspace_root).expanduser()
                    _clone_or_update_repo("Moovent", "mqtt_dashboard_watch", mqtt_branch, root / "mqtt_dashboard_watch", token)
                    _clone_or_update_repo("Moovent", "dashboard", dashboard_branch, root / "dashboard", token)

                    client_id = str(cfg.get("infisical_client_id") or "").strip()
                    client_secret = str(cfg.get("infisical_client_secret") or "").strip()
                    if client_id and client_secret:
                        _inject_infisical_env(root, client_id, client_secret)

                    _save_config(
                        {
                            "mqtt_branch": mqtt_branch,
                            "dashboard_branch": dashboard_branch,
                            "setup_complete": True,
                        }
                    )
                    state.done = True
                    self._send(200, _success_page_html())
                except Exception as exc:
                    self._send(200, _setup_step3_html([], [], f"Download failed: {exc}"))
                return

            self._send(404, "Not found", "text/plain")

    try:
        server = ThreadingHTTPServer(("127.0.0.1", _setup_port()), Handler)
    except OSError as exc:
        print(f"[setup] Unable to start local setup server: {exc}", file=sys.stderr)
        raise SystemExit(2)
    host, port = server.server_address
    setup_url = f"http://{host}:{port}/"
    state.base_url = f"http://{host}:{port}"

    print("[setup] Setup is not configured. Opening setup page…")
    print(f"[setup] {setup_url}")
    _open_browser(setup_url)

    while not state.done:
        server.handle_request()

    try:
        server.server_close()
    except Exception:
        pass


def _ttl_seconds() -> float:
    raw = os.environ.get(ACCESS_ENV_TTL, "").strip()
    if not raw:
        return DEFAULT_ACCESS_TTL_S
    try:
        value = float(raw)
        return value if value > 0 else DEFAULT_ACCESS_TTL_S
    except ValueError:
        return DEFAULT_ACCESS_TTL_S


def _install_id(cache: dict, path: Path) -> str:
    existing = cache.get("install_id")
    if isinstance(existing, str) and existing.strip():
        return existing
    new_id = secrets.token_hex(12)
    cache["install_id"] = new_id
    _save_json(path, cache)
    return new_id


def _cache_valid(cache: dict, ttl_s: float) -> bool:
    checked_at = cache.get("checked_at")
    if not isinstance(checked_at, (int, float)):
        return False
    return (time.time() - float(checked_at)) <= ttl_s


def _fetch_infisical_access(host: str, client_id: str, client_secret: str) -> tuple[Optional[bool], str]:
    """
    Validate Infisical Universal Auth credentials.

    Returns:
    - allowed: True/False if request succeeded
    - allowed: None if request failed (network/server)
    - reason: failure reason for logging
    """
    project_id, environment, secret_path = _resolve_infisical_scope()
    mismatch = _required_project_id_mismatch_reason()
    if mismatch:
        return False, mismatch

    # 1) Universal Auth login (machine identity)
    login_url = f"{host}/api/v1/auth/universal-auth/login"
    payload = {"clientId": client_id, "clientSecret": client_secret}
    body = json.dumps(payload).encode("utf-8")
    req = Request(login_url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8").strip()
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                return False, "invalid_response"
            # Accept common token fields to confirm auth
            token = str(
                data.get("accessToken") or data.get("token") or data.get("access_token") or ""
            ).strip()
            if not token:
                return False, "invalid_response"

            # 2) Enforce project access by listing secrets for the required project.
            # This mirrors mqtt_dashboard_watch (Universal Auth + list_secrets scoped to project).
            #
            # Important:
            # - We never log or print the secrets payload.
            # - Any 2xx response is sufficient proof of access.
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
            with urlopen(secrets_req, timeout=ACCESS_REQUEST_TIMEOUT_S) as secrets_resp:
                _ = secrets_resp.read()  # intentionally ignored
                return True, ""
    except HTTPError as err:
        if 400 <= err.code < 500:
            return False, f"http_{err.code}"
        return None, f"http_{err.code}"
    except Exception as exc:
        return None, f"request_failed:{exc.__class__.__name__}"


def _github_api_request(url: str, token: str) -> dict:
    """Call GitHub API with token and return JSON dict."""
    req = Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
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


def _github_list_branches(owner: str, repo: str, token: str) -> list[str]:
    """List branch names for a repo."""
    url = f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100"
    req = Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    with urlopen(req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
        raw = resp.read().decode("utf-8").strip()
        data = json.loads(raw) if raw else []
        if not isinstance(data, list):
            return []
        return [str(item.get("name") or "").strip() for item in data if isinstance(item, dict)]


def _safe_install_root(install_root: Path) -> bool:
    try:
        resolved = install_root.resolve()
    except Exception:
        return False
    if str(resolved) in {"/", str(Path.home())}:
        return False
    return "Cellar" in resolved.parts


def _self_clean(install_root: Path, cache_path: Path) -> None:
    if not _safe_install_root(install_root):
        print("[access] Cleanup skipped: unsafe install root.", file=sys.stderr)
        return
    try:
        shutil.rmtree(install_root, ignore_errors=True)
    except Exception:
        pass
    for p in [cache_path]:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            continue


def _write_env_key(path: Path, key: str, value: str) -> None:
    """
    Write or update a key in a .env file.

    Preserves existing lines and comments. Appends if missing.
    """
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    updated = False
    new_lines = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            new_lines.append(line)
            continue
        if line.split("=", 1)[0].strip() == key:
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _inject_infisical_env(workspace_root: Path, client_id: str, client_secret: str) -> None:
    """
    Inject Infisical creds into mqtt_dashboard_watch/.env.
    """
    env_path = workspace_root / "mqtt_dashboard_watch" / ".env"
    # Keep config aligned with mqtt_dashboard_watch Infisical loader env vars.
    # This prevents local runs failing due to missing project/environment settings.
    host, _, _ = _resolve_infisical_settings()
    project_id, environment, secret_path = _resolve_infisical_scope()
    _write_env_key(env_path, "INFISICAL_HOST", host)
    _write_env_key(env_path, "INFISICAL_PROJECT_ID", project_id)
    _write_env_key(env_path, "INFISICAL_ENVIRONMENT", environment)
    _write_env_key(env_path, "INFISICAL_SECRET_PATH", secret_path)
    _write_env_key(env_path, "INFISICAL_CLIENT_ID", client_id)
    _write_env_key(env_path, "INFISICAL_CLIENT_SECRET", client_secret)


def _run_git(cmd: list[str], cwd: Path) -> None:
    """Run git command with safe defaults."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    subprocess.check_call(cmd, cwd=str(cwd), env=env)


def _clone_or_update_repo(owner: str, repo: str, branch: str, dest: Path, token: str) -> None:
    """
    Clone or update a repo to the requested branch.

    Uses token-auth HTTPS URL for private repos.
    """
    repo_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
    if dest.exists() and (dest / ".git").exists():
        _run_git(["git", "fetch", "origin"], dest)
        _run_git(["git", "checkout", branch], dest)
        _run_git(["git", "pull", "origin", branch], dest)
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    _run_git(["git", "clone", "--branch", branch, repo_url, str(dest)], dest.parent)


def ensure_access_or_exit(host: str, client_id: str, client_secret: str) -> None:
    ttl_s = _ttl_seconds()
    cache_path = _cache_path()
    cache = _load_json(cache_path)
    install_id = _install_id(cache, cache_path)
    project_id, _, _ = _resolve_infisical_scope()

    if _cache_valid(cache, ttl_s):
        # Cache is only valid if it matches the required project scope.
        if cache.get("allowed") is True and cache.get("project_id") == project_id:
            return
        raise SystemExit(f"[access] Access denied (cached): {cache.get('reason', 'unknown')}")

    allowed, reason = _fetch_infisical_access(host, client_id, client_secret)
    if allowed is None:
        if cache.get("allowed") is True:
            print("[access] Infisical unreachable; using cached allow.", file=sys.stderr)
            return
        raise SystemExit("[access] Infisical auth failed and no cached allow is available.")

    cache.update(
        {
            "checked_at": time.time(),
            "allowed": bool(allowed),
            "reason": reason,
            "install_id": install_id,
            "project_id": project_id,
        }
    )
    _save_json(cache_path, cache)

    if allowed:
        return

    print(f"[access] Access denied: {reason or 'invalid_credentials'}", file=sys.stderr)
    if _env_bool(os.environ.get(ACCESS_ENV_SELF_CLEAN)):
        root_raw = os.environ.get(ACCESS_ENV_INSTALL_ROOT, "").strip()
        if root_raw:
            _self_clean(Path(root_raw), cache_path)
        else:
            print("[access] Cleanup skipped: install root not provided.", file=sys.stderr)
        raise SystemExit(3)


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception:
        print("[runner] Unable to open browser automatically.", file=sys.stderr)


def _run_local_stack(runner_path: Path) -> int:
    """Run the local stack via run_local_stack.py."""
    print("[runner] Starting local stack...")
    return subprocess.call([sys.executable, str(runner_path)])


def main() -> int:
    host, client_id, client_secret = _resolve_infisical_settings()
    runner_path = _resolve_runner_path()

    if not client_id or not client_secret or not runner_path:
        if _setup_noninteractive():
            print("[runner] Missing setup. Provide Infisical credentials and workspace path.", file=sys.stderr)
            return 2
        _run_setup_server()
        host, client_id, client_secret = _resolve_infisical_settings()
        runner_path = _resolve_runner_path()
        if not client_id or not client_secret or not runner_path:
            print("[runner] Setup incomplete. Please finish setup.", file=sys.stderr)
            return 2

    ok, error = _validate_runner_path(runner_path)
    if not ok:
        print(f"[runner] {error}", file=sys.stderr)
        return 2

    # Authenticate via Infisical Universal Auth before running the stack.
    ensure_access_or_exit(host, client_id, client_secret)
    return _run_local_stack(runner_path)


if __name__ == "__main__":
    raise SystemExit(main())
