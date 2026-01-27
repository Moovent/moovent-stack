"""
Shared configuration and environment helpers for moovent-stack.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


# ----------------------------
# Config / environment knobs
# ----------------------------
INFISICAL_ENV_ENABLED = "INFISICAL_ENABLED"
INFISICAL_ENV_HOST = "INFISICAL_HOST"
INFISICAL_ENV_CLIENT_ID = "INFISICAL_CLIENT_ID"
INFISICAL_ENV_CLIENT_SECRET = "INFISICAL_CLIENT_SECRET"
INFISICAL_ENV_PROJECT_ID = "INFISICAL_PROJECT_ID"
INFISICAL_ENV_ENVIRONMENT = "INFISICAL_ENVIRONMENT"
INFISICAL_ENV_SECRET_PATH = "INFISICAL_SECRET_PATH"
INFISICAL_ENV_DEBUG = "MOOVENT_INFISICAL_DEBUG"
GITHUB_ENV_CLIENT_ID = "MOOVENT_GITHUB_CLIENT_ID"
GITHUB_ENV_CLIENT_SECRET = "MOOVENT_GITHUB_CLIENT_SECRET"
GITHUB_ENV_ACCESS_TOKEN = "MOOVENT_GITHUB_ACCESS_TOKEN"
ACCESS_ENV_TTL = "MOOVENT_ACCESS_TTL_S"
ACCESS_ENV_SELF_CLEAN = "MOOVENT_ACCESS_SELF_CLEAN"
ACCESS_ENV_INSTALL_ROOT = "MOOVENT_INSTALL_ROOT"
ACCESS_ENV_CACHE_PATH = "MOOVENT_ACCESS_CACHE_PATH"
WORKSPACE_ENV_ROOT = "MOOVENT_WORKSPACE_ROOT"
RUNNER_ENV_PATH = "MOOVENT_RUNNER_PATH"

# Optional: which Infisical secrets to export into the local stack env at runtime.
# Format: comma-separated keys (e.g. "BROKER,MONGO_URI,...").
INFISICAL_EXPORT_KEYS_ENV = "MOOVENT_INFISICAL_EXPORT_KEYS"

SETUP_ENV_NONINTERACTIVE = "MOOVENT_SETUP_NONINTERACTIVE"
SETUP_ENV_PORT = "MOOVENT_SETUP_PORT"

DEFAULT_ACCESS_TTL_S = 24 * 60 * 60
ACCESS_REQUEST_TIMEOUT_S = 5.0
DEFAULT_SETUP_PORT = 9010

DEFAULT_CACHE_PATH = Path.home() / ".moovent_stack_access.json"
CONFIG_PATH = Path.home() / ".moovent_stack_config.json"

# Default to the EU Infisical tenant for Moovent.
# Assumption: Moovent's org/project lives in EU; override via INFISICAL_HOST if needed.
DEFAULT_INFISICAL_HOST = "https://eu.infisical.com"

DEFAULT_GITHUB_SCOPES = "repo read:org"

# Required Infisical scope (org/project) enforcement
REQUIRED_INFISICAL_ORG_ID = "20256abe-9337-498a-af56-d08d6e762d29"
REQUIRED_INFISICAL_PROJECT_ID = "b33db90d-cc5b-464e-b58c-a09e7328e83d"
DEFAULT_INFISICAL_ENVIRONMENT = "dev"
DEFAULT_INFISICAL_SECRET_PATH = "/"

# Default env keys required by mqtt_dashboard_watch backend at import time.
# These are exported from Infisical by moovent-stack at runtime (kept off disk).
DEFAULT_INFISICAL_EXPORT_KEYS = (
    "BROKER",
    "MQTT_USER",
    "MQTT_PASS",
    "MQTT_PORT",
    "MONGO_URI",
    "DB_NAME",
    "COL_DEVICES",
    "COL_PARKINGS",
    "COL_TOTALS",
    "COL_BUCKETS",
)


def _get_version() -> str:
    """Return version string from VERSION file or fallback."""
    # Try installed package location first
    install_root = os.environ.get(ACCESS_ENV_INSTALL_ROOT, "")
    if install_root:
        version_file = Path(install_root) / "VERSION"
        if version_file.exists():
            return version_file.read_text().strip()
    # Try relative to this file (dev mode)
    here = Path(__file__).parent.parent / "VERSION"
    if here.exists():
        return here.read_text().strip()
    return "dev"


def _current_year() -> int:
    """Return current year for copyright."""
    import datetime

    return datetime.datetime.now().year


__version__ = _get_version()


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
