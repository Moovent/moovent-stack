"""
Main orchestration for moovent-stack.
"""

from __future__ import annotations

import sys

from .access import ensure_access_or_exit
from .config import _setup_noninteractive
from .infisical import _resolve_infisical_settings
from .runner import _run_local_stack
from .setup.server import _run_setup_server
from .workspace import _resolve_runner_path, _validate_runner_path


def main() -> int:
    host, client_id, client_secret = _resolve_infisical_settings()
    runner_path = _resolve_runner_path()

    if not client_id or not client_secret or not runner_path:
        if _setup_noninteractive():
            print(
                "[runner] Missing setup. Provide Infisical credentials and workspace path.",
                file=sys.stderr,
            )
            return 2
        _run_setup_server()
        host, client_id, client_secret = _resolve_infisical_settings()
        runner_path = _resolve_runner_path()
        if not client_id or not client_secret or not runner_path:
            print("[runner] Setup incomplete. Please finish setup.", file=sys.stderr)
            return 2

    ok, error = _validate_runner_path(runner_path)
    if not ok:
        print(f"[runner] {error}", file=sys.stderr)
        return 2

    # Authenticate via Infisical Universal Auth before running the stack.
    ensure_access_or_exit(host, client_id, client_secret)
    return _run_local_stack(runner_path)
