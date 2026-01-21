"""
Runtime environment injection and stack launcher.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .config import (
    INFISICAL_ENV_CLIENT_ID,
    INFISICAL_ENV_CLIENT_SECRET,
    INFISICAL_ENV_ENABLED,
    INFISICAL_ENV_ENVIRONMENT,
    INFISICAL_ENV_HOST,
    INFISICAL_ENV_PROJECT_ID,
    INFISICAL_ENV_SECRET_PATH,
)
from .infisical import _resolve_infisical_scope, _resolve_infisical_settings


def _build_runner_env() -> dict[str, str]:
    """
    Build env overrides for run_local_stack.py.

    Purpose:
    - Provide Infisical "secret zero" at runtime (no disk storage).
    - Keep child processes aligned with required project scope.

    Assumption:
    - Access has already been validated by moovent-stack.
    """
    host, client_id, client_secret = _resolve_infisical_settings()
    project_id, environment, secret_path = _resolve_infisical_scope()
    overrides = {
        INFISICAL_ENV_ENABLED: "true",
        INFISICAL_ENV_PROJECT_ID: project_id,
        INFISICAL_ENV_ENVIRONMENT: environment,
        INFISICAL_ENV_SECRET_PATH: secret_path,
    }
    if host:
        overrides[INFISICAL_ENV_HOST] = host
    if client_id:
        overrides[INFISICAL_ENV_CLIENT_ID] = client_id
    if client_secret:
        overrides[INFISICAL_ENV_CLIENT_SECRET] = client_secret
    return overrides


def _run_local_stack(runner_path: Path) -> int:
    """Run the local stack via run_local_stack.py."""
    print("[runner] Starting local stack...")
    env = os.environ.copy()
    # Only fill missing keys to respect user-provided overrides.
    for key, value in _build_runner_env().items():
        if value and not env.get(key):
            env[key] = value
    return subprocess.call([sys.executable, str(runner_path)], env=env)
