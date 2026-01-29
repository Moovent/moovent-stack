"""
Main orchestration for moovent-stack.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from shutil import which

from .access import ensure_access_or_exit
from .config import _setup_noninteractive, _setup_port
from .infisical import _resolve_infisical_settings
from .log import get_log_path, log_error, log_info, log_startup
from .runner import _build_runner_env
from .setup.server import _run_setup_server
from .storage import _load_config
from .workspace import _resolve_runner_path, _validate_runner_path


def _check_homebrew_update() -> None:
    """
    Check for Homebrew package updates and auto-upgrade if available.
    
    Only runs if:
    - brew is available
    - MOOVENT_SKIP_UPDATE is not set
    """
    if os.environ.get("MOOVENT_SKIP_UPDATE", "").strip().lower() in ("1", "true", "yes"):
        return
    
    brew = which("brew")
    if not brew:
        return
    
    formula = "moovent/tap/moovent-stack"
    
    try:
        # Check if update is available (quick check)
        print("[runner] Checking for updates...", flush=True)
        log_info("app", "Checking for Homebrew updates...")
        
        # Update tap first (fetch latest formula)
        subprocess.run(
            [brew, "update", "--quiet"],
            capture_output=True,
            timeout=30,
        )
        
        # Check if outdated
        result = subprocess.run(
            [brew, "outdated", formula],
            capture_output=True,
            text=True,
            timeout=15,
        )
        
        # If formula appears in outdated list, upgrade it
        if formula in result.stdout or "moovent-stack" in result.stdout:
            print("[runner] Update available! Upgrading moovent-stack...", flush=True)
            log_info("app", "Homebrew update available, upgrading...")
            
            upgrade_result = subprocess.run(
                [brew, "upgrade", formula],
                capture_output=True,
                text=True,
                timeout=120,
            )
            
            if upgrade_result.returncode == 0:
                print("[runner] Updated! Please restart moovent-stack.", flush=True)
                log_info("app", "Homebrew upgrade successful, restart required")
                # Exit so user restarts with new version
                sys.exit(0)
            else:
                log_error("app", f"Homebrew upgrade failed: {upgrade_result.stderr}")
                print("[runner] Update failed, continuing with current version.", flush=True)
        else:
            log_info("app", "moovent-stack is up to date")
    
    except subprocess.TimeoutExpired:
        log_info("app", "Update check timed out, continuing...")
    except Exception as e:
        log_info("app", f"Update check failed: {e}")


def main() -> int:
    log_startup()
    
    # Check for Homebrew updates first
    _check_homebrew_update()
    
    log_info("app", "Resolving settings...")
    host, client_id, client_secret = _resolve_infisical_settings()
    runner_path = _resolve_runner_path()
    log_info("app", f"Runner path: {runner_path}")

    if not client_id or not client_secret or not runner_path:
        log_info("app", "Setup required (missing credentials or workspace)")
        if _setup_noninteractive():
            msg = "Missing setup. Provide Infisical credentials and workspace path."
            log_error("app", msg)
            print(f"[runner] {msg}", file=sys.stderr)
            print(f"[runner] See log: {get_log_path()}", file=sys.stderr)
            return 2
        stack_launched = _run_setup_server()
        if stack_launched:
            # Setup already started the admin dashboard in the background.
            log_info("app", "Stack was launched by setup flow; exiting setup process.")
            print("[runner] Stack is running. You can close this terminal.")
            print(f"[runner] Moovent Stack Admin: http://127.0.0.1:{_setup_port()}/")
            print("[runner] To stop all services: pkill -f moovent_stack.admin")
            return 0
        host, client_id, client_secret = _resolve_infisical_settings()
        runner_path = _resolve_runner_path()
        log_info("app", f"Post-setup runner path: {runner_path}")
        if not client_id or not client_secret or not runner_path:
            msg = "Setup incomplete. Please finish setup."
            log_error("app", msg)
            print(f"[runner] {msg}", file=sys.stderr)
            print(f"[runner] See log: {get_log_path()}", file=sys.stderr)
            return 2

    log_info("app", f"Validating workspace: {runner_path}")
    ok, error = _validate_runner_path(runner_path)
    if not ok:
        log_error("app", f"Workspace validation failed: {error}")
        print(f"[runner] {error}", file=sys.stderr)
        print(f"[runner] See log: {get_log_path()}", file=sys.stderr)
        return 2

    # Authenticate via Infisical Universal Auth before running the stack.
    log_info("app", "Authenticating with Infisical...")
    ensure_access_or_exit(host, client_id, client_secret)

    # Get workspace path from runner path
    workspace_root = runner_path.parent if runner_path else None
    if not workspace_root:
        cfg = _load_config()
        workspace_root = Path(cfg.get("workspace_root", "")).expanduser()

    if not workspace_root or not workspace_root.exists():
        log_error("app", f"Workspace not found: {workspace_root}")
        print(f"[runner] Workspace not found: {workspace_root}", file=sys.stderr)
        return 2

    # Import and run the admin dashboard directly
    log_info("app", f"Starting admin dashboard for workspace: {workspace_root}")
    
    # Load workspace .env to get MOOVENT_INFISICAL_EXPORT_KEYS before fetching secrets.
    # This allows the user to specify which additional keys to export from Infisical.
    mqtt_env_path = workspace_root / "mqtt_dashboard_watch" / ".env"
    if mqtt_env_path.exists():
        from .admin.deps import read_dotenv
        workspace_env = read_dotenv(mqtt_env_path)
        # Only load MOOVENT_INFISICAL_EXPORT_KEYS (and similar config vars) to os.environ.
        # Don't load secrets from .env — let Infisical provide those.
        config_keys = ["MOOVENT_INFISICAL_EXPORT_KEYS", "INFISICAL_REQUIRED_KEYS"]
        for k in config_keys:
            if k in workspace_env and not os.environ.get(k):
                os.environ[k] = workspace_env[k]
    
    # Inject Infisical runtime env before starting
    for k, v in _build_runner_env().items():
        if v and not os.environ.get(k):
            os.environ[k] = v

    from .admin import main as admin_main
    return admin_main(workspace_root)
