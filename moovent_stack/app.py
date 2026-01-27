"""
Main orchestration for moovent-stack.
"""

from __future__ import annotations

import sys

from .access import ensure_access_or_exit
from .config import _setup_noninteractive
from .infisical import _resolve_infisical_settings
from .log import get_log_path, log_error, log_info, log_startup
from .runner import _run_local_stack
from .setup.server import _run_setup_server
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
            # Setup already started the stack in the background; don't run again.
            log_info("app", "Stack was launched by setup flow; exiting setup process.")
            print("[runner] Stack is running. You can close this terminal.")
            print("[runner] To stop all services: pkill -f run_local_stack.py")
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
    log_info("app", "Starting local stack...")
    return _run_local_stack(runner_path)
