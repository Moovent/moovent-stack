"""
Moovent Stack Admin Dashboard.

Purpose:
  Full-featured admin UI for managing the local development stack.
  - Start/stop/restart individual services
  - View real-time logs
  - Check for and apply updates
  - Switch git branches
  - GitHub OAuth integration for repo management

Usage:
  python -m moovent_stack.admin [workspace_path]
"""

from __future__ import annotations

import os
import sys
import subprocess
import threading
import time
from pathlib import Path
from shutil import which

from .config import (
    ADMIN_BIND,
    DEFAULT_ADMIN_PORT,
    remote_mode_enabled,
    remote_url,
    remote_backend_url,
    should_open_browser,
    update_enabled,
    update_auto_pull_enabled,
    update_check_interval_s,
)
from .access import ensure_access_or_exit, open_browser
from .logs import LogStore
from .services import (
    StackManager,
    ServiceSpec,
    tcp_open_any,
    pick_free_port,
    pid_alive,
    tcp_listen_pids,
)
from .git_ops import GitCache
from .github import github_config, GitHubState
from .updates import UpdateState
from .server import build_admin_server
from .deps import read_dotenv, ensure_node_deps, ensure_python_deps
from .watchdog import ServiceWatchdog, WatchRule


def _restart_repo_services(manager: StackManager, repo: Path) -> list[str]:
    """Restart services that belong to a repo after a successful update."""
    restarted: list[str] = []
    for svc_name in manager.services_for_repo(repo):
        manager.log_store.append(svc_name, "[runner] update: restarting after git pull")
        if manager.desired_running.get(svc_name, False):
            manager.restart(svc_name)
            restarted.append(svc_name)
    return restarted


def main(workspace: Path | None = None) -> int:
    """
    Main entry point for the admin dashboard.
    
    Args:
        workspace: Path to the workspace root. If None, uses parent of this file.
    
    Returns:
        Exit code (0 for success, non-zero for errors).
    """
    if workspace is None:
        # Default: assume workspace is two levels up from this module
        workspace = Path(__file__).resolve().parent.parent.parent
    
    mqtt_repo = workspace / "mqtt_dashboard_watch"
    dashboard_repo = workspace / "dashboard"

    # Detect which repos are installed
    has_mqtt = mqtt_repo.exists()
    has_dashboard = dashboard_repo.exists()

    # Access check
    if not ensure_access_or_exit(workspace):
        return 3

    # Remote-only mode: open hosted stack and skip local services.
    if remote_mode_enabled():
        url = remote_url()
        if not url:
            print("[runner] MOOVENT_REMOTE_URL is required in remote mode.", file=sys.stderr)
            return 2
        backend = remote_backend_url()
        print("[runner] Remote mode enabled. Local services will NOT start.")
        print(f"[runner] Open: {url}")
        if backend:
            print(f"[runner] API:  {backend}")
        if should_open_browser():
            open_browser(url)
        return 0

    # Log which repos are available (not a fatal error if missing)
    if has_mqtt:
        print(f"[runner] Found repo: mqtt_dashboard_watch", flush=True)
    else:
        print(f"[runner] Repo not installed: mqtt_dashboard_watch", flush=True)
    if has_dashboard:
        print(f"[runner] Found repo: dashboard", flush=True)
    else:
        print(f"[runner] Repo not installed: dashboard", flush=True)

    # Check for npm (only required if we have repos with node deps)
    if (has_mqtt or has_dashboard) and which("npm") is None:
        print("[runner] npm not found in PATH", file=sys.stderr)
        return 2

    if not sys.executable:
        print("[runner] python executable not found", file=sys.stderr)
        return 2

    # Build list of available repos for update tracking
    available_repos: list[tuple[str, Path]] = []
    if has_mqtt:
        available_repos.append(("mqtt_dashboard_watch", mqtt_repo))
    if has_dashboard:
        available_repos.append(("dashboard", dashboard_repo))

    # Update state (only for installed repos)
    update_state = UpdateState(
        repos=available_repos,
        interval_s=update_check_interval_s(),
        enabled=update_enabled(),
        auto_pull=update_auto_pull_enabled(),
        on_repo_updated=None,
    )
    
    # Auto-pull updates once at launch when repos are clean.
    if available_repos:
        update_state.auto_pull_on_launch()

    # Install dependencies for available repos
    py_cmd = sys.executable  # Default fallback
    try:
        if has_mqtt:
            py_cmd = ensure_python_deps(mqtt_repo, sys.executable)
            ensure_node_deps(mqtt_repo / "mqtt-admin-dashboard")
        if has_dashboard:
            ensure_node_deps(dashboard_repo / "server")
            ensure_node_deps(dashboard_repo / "client")
    except subprocess.CalledProcessError as e:
        print(f"[runner] Dependency install failed: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[runner] Setup failed: {e}", file=sys.stderr)
        return 1

    # Load mqtt repo .env to auto-pick the dashboard API key when needed.
    mqtt_env: dict[str, str] = {}
    if has_mqtt:
        mqtt_env = read_dotenv(mqtt_repo / ".env")
    api_key_enforce = mqtt_env.get("API_KEY_ENFORCE", "false").strip().lower() in ("1", "true", "yes", "on")
    dashboard_api_key = (mqtt_env.get("DASHBOARD_API_KEY") or "").strip()

    client_env = dict(os.environ)
    # Always point the dashboard client to the local mqtt backend.
    client_env["VITE_REPORTS_BACKEND_BASE_URL"] = "http://localhost:8000"
    if api_key_enforce and dashboard_api_key:
        client_env["VITE_REPORTS_BACKEND_API_KEY"] = dashboard_api_key
    elif api_key_enforce and not dashboard_api_key:
        print(
            "[runner] WARNING: mqtt_dashboard_watch has API_KEY_ENFORCE=true "
            "but DASHBOARD_API_KEY is missing in mqtt_dashboard_watch/.env",
            flush=True,
        )

    # GitHub OAuth config (optional).
    github_client_id, github_client_secret = github_config()
    github_enabled = bool(github_client_id and github_client_secret)

    # Local admin UI port (optional override via env).
    admin_port = 0
    requested_admin_port = (os.environ.get("RUN_LOCAL_STACK_ADMIN_PORT") or "").strip()
    if github_enabled:
        desired_port = int(requested_admin_port) if requested_admin_port.isdigit() else DEFAULT_ADMIN_PORT
        if tcp_open_any(desired_port):
            print(
                f"[runner] WARNING: Admin port {desired_port} is in use. GitHub OAuth disabled.",
                flush=True,
            )
            github_enabled = False
            admin_port = pick_free_port(desired_port + 1)
        else:
            admin_port = desired_port
    else:
        if requested_admin_port.isdigit():
            candidate = int(requested_admin_port)
            if tcp_open_any(candidate):
                print(
                    f"[runner] WARNING: RUN_LOCAL_STACK_ADMIN_PORT={candidate} is in use. "
                    "Picking next free port.",
                    flush=True,
                )
                admin_port = pick_free_port(candidate + 1)
            else:
                admin_port = candidate
        else:
            admin_port = pick_free_port(DEFAULT_ADMIN_PORT)

    # Dashboard server port should never conflict with existing services.
    server_port = pick_free_port(5001)

    log_store = LogStore()
    git_cache = GitCache()
    github_state = GitHubState()
    # quiet=True suppresses service logs from terminal (view in dashboard instead)
    manager = StackManager(log_store, quiet=True)

    # Ensure ports align with dashboard client proxy.
    mqtt_proc_env = dict(os.environ)
    mqtt_proc_env.setdefault("PORT", "8000")
    # Keep mqtt backend usable even if MQTT broker is unreachable.
    mqtt_proc_env["ALLOW_START_WITHOUT_MQTT"] = "true"

    server_env = dict(os.environ)
    server_env["PORT"] = str(server_port)

    # Ensure the dashboard client proxies /api to the chosen server port.
    client_env = dict(client_env)
    client_env["VITE_API_PROXY_TARGET"] = f"http://localhost:{server_port}"

    # Register services only for installed repos
    if has_mqtt:
        manager.register(
            ServiceSpec(
                name="mqtt-backend",
                cmd=[py_cmd, "src/main.py"],
                cwd=mqtt_repo,
                env=mqtt_proc_env,
                url="http://localhost:8000",
                health_url="http://localhost:8000/health",
                port=8000,
                repo=mqtt_repo,
            )
        )
        manager.register(
            ServiceSpec(
                name="mqtt-frontend",
                cmd=["npm", "run", "dev", "--", "--port", "3000", "--strictPort"],
                cwd=mqtt_repo / "mqtt-admin-dashboard",
                env=dict(os.environ),
                url="http://localhost:3000",
                health_url="http://localhost:3000/",
                port=3000,
                repo=mqtt_repo,
            )
        )

    if has_dashboard:
        manager.register(
            ServiceSpec(
                name="dashboard-server",
                cmd=["npm", "run", "dev"],
                cwd=dashboard_repo / "server",
                env=server_env,
                url=f"http://localhost:{server_port}",
                # Port-only health to avoid spamming morgan logs with runner probes.
                health_url="",
                port=server_port,
                repo=dashboard_repo,
            )
        )
        manager.register(
            ServiceSpec(
                name="dashboard-client",
                cmd=["npm", "run", "dev", "--", "--port", "4000", "--strictPort"],
                cwd=dashboard_repo / "client",
                env=client_env,
                url="http://localhost:4000",
                health_url="http://localhost:4000/",
                port=4000,
                repo=dashboard_repo,
            )
        )

    # Wire update restarts now that services are registered.
    update_state.set_on_repo_updated(lambda repo: _restart_repo_services(manager, repo))

    watch_rules: list[WatchRule] = []
    if has_mqtt:
        watch_rules.extend(
            [
                WatchRule(
                    service="mqtt-backend",
                    root=mqtt_repo,
                    globs=["src/**/*.py", ".env"],
                    action="restart",
                    debounce_s=0.35,
                    reason="mqtt-backend code/env changed",
                ),
                WatchRule(
                    service="mqtt-backend",
                    root=mqtt_repo,
                    globs=["requirements.txt"],
                    action="python_reinstall_restart",
                    debounce_s=0.35,
                    reason="mqtt-backend python deps changed",
                ),
                WatchRule(
                    service="mqtt-frontend",
                    root=mqtt_repo / "mqtt-admin-dashboard",
                    globs=[
                        "package-lock.json",
                        "package.json",
                        "vite.config.*",
                        "postcss.config.*",
                        "tailwind.config.*",
                        ".env",
                        ".env.local",
                    ],
                    action="node_reinstall_restart",
                    debounce_s=0.35,
                    reason="mqtt-frontend deps/config changed",
                ),
            ]
        )
    if has_dashboard:
        watch_rules.extend(
            [
                WatchRule(
                    service="dashboard-server",
                    root=dashboard_repo / "server",
                    globs=[
                        "package-lock.json",
                        "package.json",
                        ".env",
                        ".env.local",
                    ],
                    action="node_reinstall_restart",
                    debounce_s=0.35,
                    reason="dashboard-server deps/config changed",
                ),
                WatchRule(
                    service="dashboard-client",
                    root=dashboard_repo / "client",
                    globs=[
                        "package-lock.json",
                        "package.json",
                        "vite.config.*",
                        "postcss.config.*",
                        "tailwind.config.*",
                        ".env",
                        ".env.local",
                    ],
                    action="node_reinstall_restart",
                    debounce_s=0.35,
                    reason="dashboard-client deps/config changed",
                ),
            ]
        )
    watchdog = ServiceWatchdog(watch_rules) if watch_rules else None

    # Start admin UI server.
    admin_server = build_admin_server(
        manager,
        log_store,
        git_cache,
        github_state,
        update_state,
        github_client_id if github_enabled else "",
        github_client_secret if github_enabled else "",
        ADMIN_BIND,
        admin_port,
    )
    admin_thread = threading.Thread(target=admin_server.serve_forever, daemon=True)
    admin_thread.start()

    try:
        manager.start_all()

        admin_url = f"http://{ADMIN_BIND}:{admin_port}"
        print("", flush=True)
        print("[runner] ========================================", flush=True)
        print("[runner] Moovent Stack Admin Dashboard", flush=True)
        print(f"[runner] {admin_url}", flush=True)
        print("[runner] ========================================", flush=True)
        print("[runner] View service logs in the dashboard.", flush=True)
        print("[runner] Press Ctrl+C to shutdown.", flush=True)
        print("", flush=True)

        # Auto-open browser
        if should_open_browser():
            open_browser(admin_url)

        if watchdog:
            watchdog.prime()

        while True:
            # Watchdog: restart services when config/deps/code changes require a restart.
            if watchdog:
                for event in watchdog.poll():
                    try:
                        spec = manager.services.get(event.service)
                        if not spec:
                            continue
                        if event.action == "node_reinstall_restart":
                            ensure_node_deps(spec.cwd)
                        elif event.action == "python_reinstall_restart":
                            ensure_python_deps(mqtt_repo, sys.executable)
                        manager.log_store.append(
                            event.service, f"[runner] watchdog: {event.reason}; restarting"
                        )
                        manager.restart(event.service)
                    except Exception as exc:
                        manager.log_store.append(
                            event.service,
                            f"[runner] watchdog failed: {type(exc).__name__}: {exc}",
                        )

            # Record unexpected process exits without killing the stack
            for name, proc in list(manager.procs.items()):
                code = proc.poll()
                if code is not None and manager.desired_running.get(name, False):
                    manager.note_exit(name, code)

            time.sleep(0.6)

    except KeyboardInterrupt:
        print("\n[runner] Ctrl+C received. Shutting down...", flush=True)
        # Kill everything immediately
        stop_errors: list[str] = []
        try:
            manager.stop_all()
        except Exception as exc:
            stop_errors.append(str(exc))

        # Verify shutdown (runner-owned PIDs should be gone).
        still_alive: list[tuple[str, int]] = []
        try:
            for svc_name, pid in sorted(manager.last_pids.items()):
                if pid_alive(pid):
                    still_alive.append((svc_name, pid))
        except Exception as exc:
            stop_errors.append(f"verify_failed: {exc}")

        # Diagnose remaining port listeners
        port_notes: list[str] = []
        try:
            for spec in manager.services.values():
                if not spec.port:
                    continue
                listeners = tcp_listen_pids(int(spec.port), ttl_s=0.0)
                if not listeners:
                    continue
                ours = []
                for svc_name, pid in manager.last_pids.items():
                    if pid in listeners:
                        ours.append(f"{svc_name}:{pid}")
                if ours:
                    port_notes.append(f"port {int(spec.port)} still held by runner PID(s): {', '.join(ours)}")
                else:
                    port_notes.append(
                        f"port {int(spec.port)} still has non-runner listener PID(s): "
                        f"{', '.join(str(p) for p in listeners[:5])}"
                    )
        except Exception as exc:
            stop_errors.append(f"port_check_failed: {exc}")

        if stop_errors or still_alive:
            if stop_errors:
                print(f"[runner] Shutdown warnings: {' | '.join(stop_errors)}", flush=True)
            if still_alive:
                alive_str = ", ".join(f"{n}:{p}" for n, p in still_alive)
                print(f"[runner] Shutdown incomplete: still alive: {alive_str}", flush=True)
            for note in port_notes:
                print(f"[runner] NOTE: {note}", flush=True)
        else:
            print("[runner] Shutdown complete: all runner processes stopped.", flush=True)

        return 0

    finally:
        # Idempotent safety net: stop processes even if shutdown path changes.
        try:
            manager.stop_all()
        except Exception:
            pass
        try:
            admin_server.shutdown()
        except Exception:
            pass
        try:
            admin_server.server_close()
        except Exception:
            pass


if __name__ == "__main__":
    # Allow passing workspace path as argument
    workspace_path = None
    if len(sys.argv) > 1:
        workspace_path = Path(sys.argv[1]).resolve()
    raise SystemExit(main(workspace_path))
