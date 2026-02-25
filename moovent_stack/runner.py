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
    INFISICAL_ENV_ENABLED,
    INFISICAL_ENV_ENVIRONMENT,
    INFISICAL_ENV_HOST,
    INFISICAL_ENV_PROJECT_ID,
    INFISICAL_ENV_SECRET_PATH,
    DEFAULT_INFISICAL_EXPORT_KEYS,
    INFISICAL_EXPORT_ALL_ENV,
    INFISICAL_EXPORT_KEYS_ENV,
)
from .infisical import (
    _fetch_infisical_env_all,
    _fetch_infisical_env_exports,
    _resolve_infisical_scope,
    _resolve_infisical_settings,
)
from .log import log_info


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
    # Security: do not pass secret-zero into child process env.
    # The launcher uses the secret to fetch runtime keys, then injects only
    # the resolved stack settings/secrets needed by child services.

    # Export required stack secrets (BROKER/MONGO/etc.) from Infisical at runtime.
    # This keeps secrets off disk and avoids startup crashes in mqtt_dashboard_watch.
    export_all = str(os.environ.get(INFISICAL_EXPORT_ALL_ENV, "")).strip()
    raw_keys = os.environ.get(INFISICAL_EXPORT_KEYS_ENV, "").strip()
    # Always include the required baseline keys so the stack can start.
    # If the user provides an override list, we treat it as "plus these keys".
    keys = set(DEFAULT_INFISICAL_EXPORT_KEYS)
    if raw_keys:
        keys.update([k.strip() for k in raw_keys.split(",") if k.strip()])
    keys_list = sorted(keys)
    if host and client_id and client_secret:
        if export_all and export_all.lower() in {"1", "true", "yes", "y", "on"}:
            exported = _fetch_infisical_env_all(host, client_id, client_secret)
        else:
            exported = _fetch_infisical_env_exports(host, client_id, client_secret, keys_list)
        # Do not override user-provided env keys (caller fills missing only),
        # but include them in overrides for the merge step.
        overrides.update(exported)
        log_info("runner", f"Runtime env exports: {len(exported)} keys")
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
