"""
Admin UI configuration constants and environment helpers.

Purpose:
  Centralize all config knobs, defaults, and env-parsing for the admin dashboard.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Network / ports
# ---------------------------------------------------------------------------
ADMIN_BIND = "127.0.0.1"
DEFAULT_ADMIN_PORT = 9000  # Avoids macOS AirPlay conflict on 5000/7000

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
DEFAULT_LOG_TAIL = 200
MAX_LOG_LINES = 2000

# ---------------------------------------------------------------------------
# Git / update
# ---------------------------------------------------------------------------
GIT_CACHE_TTL_S = 3.0
GIT_BRANCH_LIMIT = 200
UPDATE_DEFAULT_CHECK_INTERVAL_S = 60 * 60
UPDATE_MIN_CHECK_INTERVAL_S = 60.0
UPDATE_GIT_TIMEOUT_S = 20.0

# ---------------------------------------------------------------------------
# GitHub OAuth
# ---------------------------------------------------------------------------
GITHUB_OAUTH_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_OAUTH_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_SCOPES = "repo read:org"
GITHUB_REPOS_CACHE_TTL_S = 30.0
GITHUB_BRANCHES_CACHE_TTL_S = 30.0

# ---------------------------------------------------------------------------
# Config / cache files
# ---------------------------------------------------------------------------
# Use the SAME config file as setup so credentials carry over
CONFIG_FILE_PATH = Path.home() / ".moovent_stack_config.json"
ACCESS_CACHE_PATH_DEFAULT = Path.home() / ".moovent_stack_access.json"

# ---------------------------------------------------------------------------
# Access control env vars
# ---------------------------------------------------------------------------
ACCESS_DEFAULT_TTL_S = 24 * 60 * 60
ACCESS_REQUEST_TIMEOUT_S = 5.0
ACCESS_ENV_URL = "MOOVENT_ACCESS_URL"
ACCESS_ENV_TOKEN = "MOOVENT_ACCESS_TOKEN"
ACCESS_ENV_TTL = "MOOVENT_ACCESS_TTL_S"
ACCESS_ENV_SELF_CLEAN = "MOOVENT_ACCESS_SELF_CLEAN"
ACCESS_ENV_INSTALL_ROOT = "MOOVENT_INSTALL_ROOT"
ACCESS_ENV_CACHE_PATH = "MOOVENT_ACCESS_CACHE_PATH"

# ---------------------------------------------------------------------------
# Remote mode env vars
# ---------------------------------------------------------------------------
REMOTE_ENV_ENABLED = "MOOVENT_REMOTE_MODE"
REMOTE_ENV_URL = "MOOVENT_REMOTE_URL"
REMOTE_ENV_BACKEND_URL = "MOOVENT_REMOTE_BACKEND_URL"
REMOTE_ENV_OPEN_BROWSER = "MOOVENT_REMOTE_OPEN_BROWSER"

# ---------------------------------------------------------------------------
# Update env vars
# ---------------------------------------------------------------------------
UPDATE_ENV_ENABLED = "MOOVENT_AUTOUPDATE_ENABLED"
UPDATE_ENV_CHECK_INTERVAL = "MOOVENT_AUTOUPDATE_CHECK_INTERVAL_S"
UPDATE_ENV_AUTO_PULL = "MOOVENT_AUTOUPDATE_AUTOPULL"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
def env_bool(value: Optional[str]) -> bool:
    """Parse a bool-like env var value safely."""
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_bool_default(value: Optional[str], default: bool) -> bool:
    """Parse a bool-like env var with a safe default."""
    if value is None or not value.strip():
        return default
    return env_bool(value)


def update_enabled() -> bool:
    """Return True when auto-update checks are enabled (default: True)."""
    return env_bool_default(os.environ.get(UPDATE_ENV_ENABLED), True)


def update_auto_pull_enabled() -> bool:
    """
    Return True when auto-pull on launch is enabled (default: True).

    Purpose:
      Keeps local repos fresh on startup when the worktree is clean.
    """
    return env_bool_default(os.environ.get(UPDATE_ENV_AUTO_PULL), True)


def update_check_interval_s() -> float:
    """
    Parse the update check interval (seconds).

    Edge case:
      Enforce a small minimum to avoid hammering git remotes.
    """
    raw = os.environ.get(UPDATE_ENV_CHECK_INTERVAL, "").strip()
    if not raw:
        return UPDATE_DEFAULT_CHECK_INTERVAL_S
    try:
        value = float(raw)
    except ValueError:
        return UPDATE_DEFAULT_CHECK_INTERVAL_S
    return max(UPDATE_MIN_CHECK_INTERVAL_S, value)


def remote_mode_enabled() -> bool:
    """Check if remote-only mode is enabled."""
    return env_bool(os.environ.get(REMOTE_ENV_ENABLED))


def remote_url() -> Optional[str]:
    """Get the remote stack URL (for remote mode)."""
    return os.environ.get(REMOTE_ENV_URL, "").strip() or None


def remote_backend_url() -> Optional[str]:
    """Get the remote backend URL (for remote mode)."""
    return os.environ.get(REMOTE_ENV_BACKEND_URL, "").strip() or None


def should_open_browser() -> bool:
    """Check if browser should be opened automatically."""
    return env_bool_default(os.environ.get(REMOTE_ENV_OPEN_BROWSER), True)


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------
def load_config() -> dict:
    """Load config from the config file (if it exists)."""
    if not CONFIG_FILE_PATH.exists():
        return {}
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(config: dict) -> bool:
    """Save config to the config file. Returns True on success."""
    try:
        with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        return True
    except Exception:
        return False
