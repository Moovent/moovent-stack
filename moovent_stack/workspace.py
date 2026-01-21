"""
Workspace validation and repo management.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .config import RUNNER_ENV_PATH, WORKSPACE_ENV_ROOT
from .infisical import _resolve_infisical_scope, _resolve_infisical_settings
from .storage import _load_config


def _resolve_runner_path() -> Optional[Path]:
    """Resolve the path to run_local_stack.py."""
    raw_runner = os.environ.get(RUNNER_ENV_PATH, "").strip()
    if raw_runner:
        return Path(raw_runner).expanduser()

    raw_root = os.environ.get(WORKSPACE_ENV_ROOT, "").strip()
    if raw_root:
        return Path(raw_root).expanduser() / "run_local_stack.py"

    cfg = _load_config()
    root = str(cfg.get("workspace_root") or "").strip()
    if root:
        return Path(root).expanduser() / "run_local_stack.py"

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


def _default_workspace_path() -> str:
    """Return sensible default workspace path based on OS."""
    home = Path.home()
    docs = home / "Documents" / "Moovent-stack"
    return str(docs)


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


def _inject_infisical_env(workspace_root: Path) -> None:
    """
    Inject Infisical scope config into mqtt_dashboard_watch/.env.

    Purpose:
    - Keep `.env` non-sensitive (no secret zero stored on disk).
    - Pass Infisical client credentials at runtime via moovent-stack instead.
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


def _run_git(cmd: list[str], cwd: Path) -> None:
    """Run git command with safe defaults."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    subprocess.check_call(cmd, cwd=str(cwd), env=env)


def _clone_or_update_repo(
    owner: str, repo: str, branch: str, dest: Path, token: str
) -> None:
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
