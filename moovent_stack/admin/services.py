"""
Service/process management for the admin dashboard.

Purpose:
  Start, stop, restart services. Track PIDs, uptime, health status.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from shutil import which

from .logs import LogStore


@dataclass
class ServiceSpec:
    """Specification for a single service."""
    name: str
    cmd: list[str]
    cwd: Path
    env: dict[str, str]
    url: str
    health_url: str
    port: int
    repo: Optional[Path] = None


def _which(cmd: str) -> Optional[str]:
    """Find executable in PATH."""
    return which(cmd)


def _popen(*, cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    """Start a subprocess with proper settings per platform."""
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        return subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
    else:
        return subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )


def _terminate(name: str, proc: subprocess.Popen, timeout_s: float = 8.0) -> None:
    """Terminate a process gracefully, then force-kill if needed."""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            proc.terminate()
        else:
            # Send SIGTERM to process group
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                proc.terminate()
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        try:
            if sys.platform == "win32":
                proc.kill()
            else:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    proc.kill()
            proc.wait(timeout=2.0)
        except Exception:
            pass
    except Exception:
        pass


def tcp_open_any(port: int, timeout_s: float = 0.6) -> bool:
    """Check if a port is open (something is listening)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout_s):
            return True
    except (OSError, socket.timeout):
        return False


def tcp_listen_pids(port: int, *, ttl_s: float = 2.0) -> list[int]:
    """Get PIDs of processes listening on a port (macOS/Linux only)."""
    if sys.platform == "win32":
        return []
    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            timeout=ttl_s,
        )
        if result.returncode != 0:
            return []
        pids = []
        for line in result.stdout.strip().split("\n"):
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        return pids
    except Exception:
        return []


def pid_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def pick_free_port(start: int, *, limit: int = 50) -> int:
    """Find a free port starting from `start`."""
    for offset in range(limit):
        port = start + offset
        if not tcp_open_any(port, timeout_s=0.2):
            return port
    return start + limit


def http_ok(url: str, timeout_s: float = 1.5) -> tuple[bool, str]:
    """Check if an HTTP endpoint returns 2xx."""
    try:
        from urllib.request import urlopen
        from urllib.error import URLError, HTTPError
        
        with urlopen(url, timeout=timeout_s) as resp:
            return (200 <= resp.status < 300, f"HTTP {resp.status}")
    except HTTPError as e:
        return (False, f"HTTP {e.code}")
    except URLError as e:
        return (False, str(e.reason)[:50])
    except Exception as e:
        return (False, str(e)[:50])


class StackManager:
    """
    Process manager for the local stack. Keeps logs + desired state.
    """

    def __init__(self, log_store: LogStore, quiet: bool = True) -> None:
        self.services: dict[str, ServiceSpec] = {}
        self.procs: dict[str, subprocess.Popen] = {}
        self.start_times: dict[str, float] = {}
        self.desired_running: dict[str, bool] = {}
        self.restart_counts: dict[str, int] = {}
        self.last_exit_codes: dict[str, int] = {}
        # Track last known PIDs even after we remove entries from `self.procs`.
        # This helps us verify shutdown and diagnose port conflicts.
        self.last_pids: dict[str, int] = {}
        self._lock = threading.Lock()
        self.log_store = log_store
        # If quiet=True, service logs go only to log_store, not to terminal
        self.quiet = quiet

    def register(self, spec: ServiceSpec) -> None:
        self.services[spec.name] = spec
        self.desired_running.setdefault(spec.name, True)
        self.restart_counts.setdefault(spec.name, 0)

    def services_for_repo(self, repo: Path) -> list[str]:
        """Return service names that share the same repo root."""
        target = repo.resolve()
        out: list[str] = []
        for name, spec in self.services.items():
            if not spec.repo:
                continue
            if spec.repo.resolve() == target:
                out.append(name)
        return out

    def start(self, name: str) -> bool:
        spec = self.services.get(name)
        if not spec:
            return False
        with self._lock:
            proc = self.procs.get(name)
            if proc and proc.poll() is None:
                return True
            self.desired_running[name] = True
            new_proc = _popen(cmd=spec.cmd, cwd=spec.cwd, env=spec.env)
            self.procs[name] = new_proc
            self.start_times[name] = time.time()
            if getattr(new_proc, "pid", None):
                self.last_pids[name] = int(new_proc.pid)
            self.log_store.append(name, f"[runner] started (pid={new_proc.pid})")
            threading.Thread(target=self._stream_proc, args=(name, new_proc), daemon=True).start()
            return True

    def stop(self, name: str) -> bool:
        spec = self.services.get(name)
        if not spec:
            return False
        with self._lock:
            proc = self.procs.pop(name, None)
            self.desired_running[name] = False
            if not proc:
                return True
            if getattr(proc, "pid", None):
                self.last_pids[name] = int(proc.pid)
            _terminate(name, proc)
            self.log_store.append(name, "[runner] stopped")
            return True

    def restart(self, name: str) -> bool:
        spec = self.services.get(name)
        if not spec:
            return False
        self.restart_counts[name] = self.restart_counts.get(name, 0) + 1
        self.log_store.append(name, "[runner] restart requested")
        # Stop -> wait -> start (prevents transient EADDRINUSE on fast restarts).
        old_pid = None
        try:
            proc = self.procs.get(name)
            if proc and getattr(proc, "pid", None):
                old_pid = int(proc.pid)
        except Exception:
            old_pid = None

        self.stop(name)

        # Wait briefly for the old process/port to release.
        # If the port is held by a different PID, do not start (avoids flapping).
        if spec.port:
            deadline = time.time() + 8.0
            while time.time() < deadline:
                listeners = tcp_listen_pids(int(spec.port), ttl_s=0.25)
                if not listeners and not tcp_open_any(int(spec.port), timeout_s=0.2):
                    break
                if old_pid is not None and listeners and any(p != old_pid for p in listeners):
                    self.log_store.append(
                        name,
                        f"[runner] restart blocked: port {int(spec.port)} in use by PID(s): {', '.join(str(p) for p in listeners[:5])}",
                    )
                    return False
                time.sleep(0.25)

        return self.start(name)

    def start_all(self) -> None:
        for name in self.services:
            self.start(name)

    def stop_all(self) -> None:
        # Stop in a stable order; avoid iterating while mutating `self.procs`.
        for name in list(self.services.keys()):
            self.stop(name)

    def restart_all(self) -> None:
        for name in self.services:
            self.restart(name)

    def switch_repo_environment(self, name: str, environment: str) -> bool:
        """
        Switch a service to a different Infisical environment and restart.
        
        This fetches fresh secrets from the specified environment and updates
        the service's env dict before restarting.
        
        Args:
            name: Service name
            environment: Infisical environment (e.g., "dev", "prod")
            
        Returns:
            True if service was restarted successfully
        """
        spec = self.services.get(name)
        if not spec:
            return False
        
        # Import here to avoid circular imports
        from ..infisical import _fetch_secrets_for_environment
        from ..config import DEFAULT_INFISICAL_EXPORT_KEYS, INFISICAL_EXPORT_KEYS_ENV
        import os
        
        # Get the list of keys to export (defaults + any user-specified extras)
        keys = set(DEFAULT_INFISICAL_EXPORT_KEYS)
        raw_extra = os.environ.get(INFISICAL_EXPORT_KEYS_ENV, "").strip()
        if raw_extra:
            keys.update([k.strip() for k in raw_extra.split(",") if k.strip()])
        
        # Fetch secrets from the new environment
        new_secrets = _fetch_secrets_for_environment(environment, list(keys))
        
        if new_secrets:
            # Update the service's env dict with new secrets
            # (don't overwrite existing non-secret env vars)
            for key, value in new_secrets.items():
                spec.env[key] = value
            
            # Also set INFISICAL_ENVIRONMENT so the service knows which env it's in
            spec.env["INFISICAL_ENVIRONMENT"] = environment
            
            self.log_store.append(name, f"[runner] injected {len(new_secrets)} secrets from env={environment}")
        else:
            self.log_store.append(name, f"[runner] WARNING: no secrets fetched from env={environment}")
        
        return self.restart(name)

    def is_running(self, name: str) -> bool:
        proc = self.procs.get(name)
        if not proc:
            return False
        return proc.poll() is None

    def status_snapshot(self) -> list[dict[str, object]]:
        out: list[dict[str, object]] = []
        for name, spec in self.services.items():
            proc = self.procs.get(name)
            code = proc.poll() if proc else None
            running = proc is not None and code is None
            uptime_s = (time.time() - self.start_times.get(name, time.time())) if running else None
            port_open = tcp_open_any(spec.port) if spec.port else False
            
            # Health checks
            if running:
                if spec.health_url:
                    health_ok, health_status = http_ok(spec.health_url)
                else:
                    health_ok = bool(port_open)
                    health_status = "PORT open" if port_open else "PORT closed"
            else:
                health_ok, health_status = (False, "n/a")
            
            if code is not None:
                self.last_exit_codes[name] = code
            
            # Detect alerts from recent logs
            alert = None
            if running and (not health_ok or not port_open):
                alert = self.log_store.detect_alert(name, lookback=60)
                if alert and alert.get("type") == "port_in_use" and spec.port:
                    alert = dict(alert)
                    alert["port"] = int(spec.port)
                    alert["listener_pids"] = tcp_listen_pids(int(spec.port))[:5]
            
            # Get current Infisical environment for this repo
            infisical_env = spec.env.get("INFISICAL_ENVIRONMENT", "dev") if spec.env else "dev"
            
            out.append({
                "name": name,
                "pid": getattr(proc, "pid", None) if proc else None,
                "running": running,
                "exit_code": code,
                "uptime_s": uptime_s,
                "url": spec.url,
                "health_url": spec.health_url,
                "port": spec.port,
                "port_open": port_open,
                "health_ok": health_ok,
                "health_status": health_status,
                "restart_count": self.restart_counts.get(name, 0),
                "desired_running": self.desired_running.get(name, False),
                "repo_root": str(spec.repo) if spec.repo else "",
                "repo_name": spec.repo.name if spec.repo else "",
                "infisical_env": infisical_env,
                "alert": alert,
            })
        return out

    def note_exit(self, name: str, code: int) -> None:
        """Record unexpected exits without killing the whole stack."""
        last = self.last_exit_codes.get(name)
        if last == code:
            return
        self.last_exit_codes[name] = code
        self.log_store.append(name, f"[runner] process exited with code {code}")

    def _stream_proc(self, name: str, proc: subprocess.Popen) -> None:
        """Stream child stdout to log store (and optionally terminal)."""
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                line = line.rstrip("\n")
                if not line:
                    continue
                # Only print to terminal if not in quiet mode
                if not self.quiet:
                    print(f"[{name}] {line}", flush=True)
                self.log_store.append(name, line)
        except Exception as exc:
            if not self.quiet:
                print(f"[runner] log stream error for {name}: {exc}", flush=True)


def restart_repo_services(manager: StackManager, repo: Path) -> list[str]:
    """
    Restart services that belong to a repo after a successful update.

    Assumption:
      Only restart services that were previously desired to be running.
    """
    restarted: list[str] = []
    for svc_name in manager.services_for_repo(repo):
        manager.log_store.append(svc_name, "[runner] update: restarting after git pull")
        if manager.desired_running.get(svc_name, False):
            manager.restart(svc_name)
            restarted.append(svc_name)
    return restarted
