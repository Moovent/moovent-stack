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


def _config_bool(value: object, default: bool) -> bool:
    """
    Convert config values into booleans with a safe default.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _validate_runner_path(
    path: Path, *, config_override: Optional[dict] = None
) -> tuple[bool, str]:
    """
    Validate workspace layout for local stack.

    Behavior:
      - If setup selections exist, require only the selected repos.
      - If no selections exist, infer required repos from what is present.
      - At least one repo must be available.
    """
    if not path.exists():
        return False, f"run_local_stack.py not found at: {path}"
    root = path.parent
    cfg = config_override if config_override is not None else _load_config()
    mqtt_exists = (root / "mqtt_dashboard_watch").exists()
    dash_exists = (root / "dashboard").exists()

    has_install_mqtt = "install_mqtt" in cfg
    has_install_dashboard = "install_dashboard" in cfg
    if has_install_mqtt or has_install_dashboard:
        require_mqtt = _config_bool(cfg.get("install_mqtt"), True)
        require_dashboard = _config_bool(cfg.get("install_dashboard"), True)
        if not require_mqtt and not require_dashboard:
            return False, "No repositories selected for installation."
    else:
        if mqtt_exists or dash_exists:
            require_mqtt = mqtt_exists
            require_dashboard = dash_exists
        else:
            require_mqtt = True
            require_dashboard = False

    missing = []
    if require_mqtt and not mqtt_exists:
        missing.append("mqtt_dashboard_watch/")
    if require_dashboard and not dash_exists:
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
    if not env_path.parent.exists():
        # mqtt repo not installed; nothing to inject yet.
        return
    # Keep config aligned with mqtt_dashboard_watch Infisical loader env vars.
    # This prevents local runs failing due to missing project/environment settings.
    host, _, _ = _resolve_infisical_settings()
    project_id, environment, secret_path = _resolve_infisical_scope()
    _write_env_key(env_path, "INFISICAL_HOST", host)
    _write_env_key(env_path, "INFISICAL_PROJECT_ID", project_id)
    _write_env_key(env_path, "INFISICAL_ENVIRONMENT", environment)
    _write_env_key(env_path, "INFISICAL_SECRET_PATH", secret_path)


def _ensure_mqtt_admin_dashboard_shadcn_utils(workspace_root: Path) -> None:
    """
    Ensure mqtt-admin-dashboard has `src/lib/utils.js` (shadcn-style `cn()` helper).

    Why:
      Some UI components import `cn` from `@/lib/utils`, but the file can be missing
      in certain branches. This causes Vite to fail to start with:
        Failed to resolve import "@/lib/utils"

    Behavior:
      - Create the file if missing (do not overwrite).
      - Keep it minimal and dependency-aligned with existing package.json.
    """
    utils_path = (
        workspace_root
        / "mqtt_dashboard_watch"
        / "mqtt-admin-dashboard"
        / "src"
        / "lib"
        / "utils.js"
    )
    if utils_path.exists():
        return
    utils_path.parent.mkdir(parents=True, exist_ok=True)
    utils_path.write_text(
        "\n".join(
            [
                'import clsx from "clsx";',
                'import { twMerge } from "tailwind-merge";',
                "",
                "/**",
                " * Merge Tailwind class names safely.",
                " *",
                " * Purpose:",
                " *  - Used by shadcn/ui-style components (e.g. `@/components/ui/*`).",
                " */",
                "export function cn(...inputs) {",
                "  return twMerge(clsx(inputs));",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _ensure_workspace_runner(workspace_root: Path) -> None:
    """
    Ensure `<workspace>/run_local_stack.py` exists.

    Why:
      The launcher expects a workspace-level runner script. This script delegates
      to the admin module in moovent-stack for the full dashboard experience.

    Behavior:
      - If the file exists and doesn't have our marker: do nothing (user custom script).
      - If missing or has our marker: write/update the thin launcher.
    """
    runner_path = workspace_root / "run_local_stack.py"
    marker = "run_local_stack.py (generated by moovent-stack)"

    if runner_path.exists():
        try:
            existing = runner_path.read_text(encoding="utf-8")
        except Exception:
            return
        if marker not in existing:
            # User has a custom script; don't overwrite
            return

    content = '''#!/usr/bin/env python3
"""
run_local_stack.py (generated by moovent-stack)

Purpose:
  Launch the Moovent Stack Admin Dashboard.

Notes:
  - This file delegates to `python -m moovent_stack.admin`.
  - The admin module provides: service control, logs, updates, GitHub integration.
  - To customize, replace this file (the marker comment triggers auto-update).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    workspace = Path(__file__).resolve().parent

    # Try running the admin module from moovent-stack
    try:
        result = subprocess.run(
            [sys.executable, "-m", "moovent_stack.admin", str(workspace)],
            check=False,
        )
        return result.returncode
    except FileNotFoundError:
        print("[runner] moovent-stack not installed. Install with: pip install moovent-stack")
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

    try:
        runner_path.write_text(content, encoding="utf-8")
        runner_path.chmod(0o755)
    except Exception:
        pass


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
