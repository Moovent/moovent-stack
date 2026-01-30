"""
Local config/cache storage helpers.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .config import CONFIG_PATH


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


# ---------------------------------------------------------------------------
# Per-repo Infisical environment storage
# ---------------------------------------------------------------------------
def _get_repo_environment(repo_name: str, default: str = "dev") -> str:
    """
    Get the Infisical environment for a specific repo.
    
    Returns the saved environment or the default if not set.
    """
    cfg = _load_config()
    repo_envs = cfg.get("repo_environments") or {}
    return repo_envs.get(repo_name, default)


def _set_repo_environment(repo_name: str, environment: str) -> None:
    """
    Save the Infisical environment preference for a specific repo.
    """
    cfg = _load_config()
    repo_envs = cfg.get("repo_environments") or {}
    repo_envs[repo_name] = environment
    cfg["repo_environments"] = repo_envs
    _save_json(CONFIG_PATH, cfg)


def _get_all_repo_environments() -> dict[str, str]:
    """
    Get all saved repo environment preferences.
    
    Returns dict of repo_name -> environment.
    """
    cfg = _load_config()
    return cfg.get("repo_environments") or {}
