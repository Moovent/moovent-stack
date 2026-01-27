"""
Main orchestration for moovent-stack.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .access import ensure_access_or_exit
from .config import _setup_noninteractive, _setup_port
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
            # Start a lightweight Moovent Stack UI on the setup port (9000 by default).
            # This is a separate process so the user can close the terminal.
            try:
                ui_log_path = Path.home() / ".moovent_stack_ui.log"
                ui_log = open(ui_log_path, "w")  # noqa: SIM115
                env = os.environ.copy()
                subprocess.Popen(  # noqa: S603
                    [sys.executable, "-m", "moovent_stack.control"],
                    env=env,
                    start_new_session=True,
                    stdout=ui_log,
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.DEVNULL,
                )
                log_info("app", f"Moovent Stack UI launched on port {_setup_port()} (log: {ui_log_path})")
            except Exception as exc:
                log_error("app", f"Unable to start Moovent Stack UI: {exc}")
            print("[runner] Stack is running. You can close this terminal.")
            print(f"[runner] Moovent Stack UI: http://localhost:{_setup_port()}/")
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
    # Start the Moovent Stack UI in the background so it's always available on port 9000.
    # If it's already running, the child will exit quickly with "address already in use".
    try:
        ui_log_path = Path.home() / ".moovent_stack_ui.log"
        ui_log = open(ui_log_path, "w")  # noqa: SIM115
        env = os.environ.copy()
        subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "moovent_stack.control"],
            env=env,
            start_new_session=True,
            stdout=ui_log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
        )
        log_info("app", f"Moovent Stack UI launched on port {_setup_port()} (log: {ui_log_path})")
    except Exception as exc:
        log_error("app", f"Unable to start Moovent Stack UI: {exc}")
    log_info("app", "Starting local stack...")
    return _run_local_stack(runner_path)
