"""
Main orchestration for moovent-stack.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .access import ensure_access_or_exit
from .config import _setup_noninteractive, _setup_port
from .infisical import _resolve_infisical_settings
from .log import get_log_path, log_error, log_info, log_startup
from .runner import _build_runner_env
from .setup.server import _run_setup_server
from .storage import _load_config
from .workspace import _resolve_runner_path, _validate_runner_path


def main() -> int:
    log_startup()
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
    
    # Inject Infisical runtime env before starting
    import os
    for k, v in _build_runner_env().items():
        if v and not os.environ.get(k):
            os.environ[k] = v

    from .admin import main as admin_main
    return admin_main(workspace_root)
