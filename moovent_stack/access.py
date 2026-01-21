"""
Access cache and enforcement logic.
"""

from __future__ import annotations

import os
import secrets
import sys
import time
from pathlib import Path

from .config import (
    ACCESS_ENV_INSTALL_ROOT,
    ACCESS_ENV_SELF_CLEAN,
    ACCESS_ENV_TTL,
    DEFAULT_ACCESS_TTL_S,
)
from .config import _cache_path, _env_bool
from .infisical import _fetch_infisical_access, _resolve_infisical_scope
from .storage import _load_json, _save_json
from .workspace import _self_clean


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


def ensure_access_or_exit(host: str, client_id: str, client_secret: str) -> None:
    ttl_s = _ttl_seconds()
    cache_path = _cache_path()
    cache = _load_json(cache_path)
    install_id = _install_id(cache, cache_path)
    project_id, _, _ = _resolve_infisical_scope()

    # Cache is only valid if:
    # - still within TTL
    # - bound to the required project (prevents stale cache across scope changes)
    if _cache_valid(cache, ttl_s) and cache.get("project_id") == project_id:
        if cache.get("allowed") is True:
            return
        raise SystemExit(
            f"[access] Access denied (cached): {cache.get('reason', 'unknown')}"
        )

    allowed, reason = _fetch_infisical_access(host, client_id, client_secret)
    if allowed is None:
        if cache.get("allowed") is True:
            print(
                "[access] Infisical unreachable; using cached allow.", file=sys.stderr
            )
            return
        raise SystemExit(
            "[access] Infisical auth failed and no cached allow is available."
        )

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
            print(
                "[access] Cleanup skipped: install root not provided.", file=sys.stderr
            )
        raise SystemExit(3)
