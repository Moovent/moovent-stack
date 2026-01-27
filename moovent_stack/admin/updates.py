"""
Update checking and auto-pull for the admin dashboard.

Purpose:
  Background update detection, one-click updates, auto-pull on launch.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .config import (
    UPDATE_MIN_CHECK_INTERVAL_S,
    update_enabled,
    update_auto_pull_enabled,
    update_check_interval_s,
)
from .git_ops import git_update_status, git_pull_ff


class UpdateState:
    """
    Track update availability and allow manual update runs.

    Behavior:
      - Checks are cached to avoid frequent git fetches.
      - Updates only run on demand (or at launch if enabled).
    """

    def __init__(
        self,
        repos: list[tuple[str, Path]],
        interval_s: float,
        enabled: bool,
        auto_pull: bool,
        on_repo_updated: Optional[Callable[[Path], list[str]]] = None,
    ) -> None:
        self._repos = repos
        self._interval_s = max(float(interval_s), UPDATE_MIN_CHECK_INTERVAL_S)
        self._enabled = bool(enabled)
        self._auto_pull = bool(auto_pull)
        self._on_repo_updated = on_repo_updated
        self._lock = threading.Lock()
        self._checked_at = 0.0
        self._checking = False
        self._update_running = False
        self._last_error = ""
        self._last_update_at = 0.0
        self._last_update_reason = ""
        self._last_update_results: list[dict[str, object]] = []
        self._cached_status: list[dict[str, object]] = []

    def set_on_repo_updated(self, callback: Optional[Callable[[Path], list[str]]]) -> None:
        """
        Set the callback invoked after a successful git pull.

        Use case:
          Wire this after StackManager is built so updated repos restart cleanly.
        """
        with self._lock:
            self._on_repo_updated = callback

    def status(self, force_check: bool = False) -> dict[str, object]:
        """
        Get update status for all repos.
        
        If force_check is True, fetches fresh from git.
        """
        with self._lock:
            if self._checking:
                return {
                    "checking": True,
                    "enabled": self._enabled,
                    "repos": self._cached_status,
                    "last_error": self._last_error,
                }
        
        # Check if we need to refresh
        now = time.time()
        stale = (now - self._checked_at) > self._interval_s
        
        if force_check or (self._enabled and stale):
            self._run_check()
        
        with self._lock:
            return {
                "checking": self._checking,
                "enabled": self._enabled,
                "repos": list(self._cached_status),
                "last_error": self._last_error,
                "checked_at": self._checked_at,
                "interval_s": self._interval_s,
            }

    def _run_check(self) -> None:
        """Run update check for all repos."""
        with self._lock:
            if self._checking:
                return
            self._checking = True
            self._last_error = ""
        
        try:
            results: list[dict[str, object]] = []
            for name, repo_path in self._repos:
                status = git_update_status(repo_path)
                results.append({
                    "name": name,
                    "path": str(repo_path),
                    **status,
                })
            
            with self._lock:
                self._cached_status = results
                self._checked_at = time.time()
        except Exception as e:
            with self._lock:
                self._last_error = str(e)
        finally:
            with self._lock:
                self._checking = False

    def has_updates(self) -> bool:
        """Check if any repo has updates available."""
        with self._lock:
            return any(r.get("has_update", False) for r in self._cached_status)

    def run_update(self, reason: str = "manual") -> dict[str, object]:
        """
        Pull updates for all repos that have them.
        
        Returns update result with per-repo status.
        """
        with self._lock:
            if self._update_running:
                return {"success": False, "error": "update_already_running"}
            self._update_running = True
            self._last_update_reason = reason
        
        results: list[dict[str, object]] = []
        callback = None
        
        with self._lock:
            callback = self._on_repo_updated
        
        try:
            for name, repo_path in self._repos:
                # Get current status
                status = git_update_status(repo_path)
                
                if not status.get("has_update"):
                    results.append({
                        "name": name,
                        "path": str(repo_path),
                        "updated": False,
                        "reason": "no_update_available",
                    })
                    continue
                
                if status.get("dirty"):
                    results.append({
                        "name": name,
                        "path": str(repo_path),
                        "updated": False,
                        "reason": "dirty_worktree",
                    })
                    continue
                
                branch = status.get("branch", "main")
                if not branch or branch == "HEAD":
                    branch = "main"
                
                ok, msg = git_pull_ff(repo_path, str(branch))
                
                if ok:
                    results.append({
                        "name": name,
                        "path": str(repo_path),
                        "updated": True,
                        "message": msg,
                    })
                    
                    # Invoke callback to restart services
                    if callback:
                        try:
                            restarted = callback(repo_path)
                            results[-1]["restarted_services"] = restarted
                        except Exception as e:
                            results[-1]["restart_error"] = str(e)
                else:
                    results.append({
                        "name": name,
                        "path": str(repo_path),
                        "updated": False,
                        "error": msg,
                    })
            
            with self._lock:
                self._last_update_at = time.time()
                self._last_update_results = results
            
            # Refresh status after update
            self._run_check()
            
            return {
                "success": True,
                "results": results,
                "reason": reason,
            }
        
        except Exception as e:
            return {"success": False, "error": str(e)}
        
        finally:
            with self._lock:
                self._update_running = False

    def auto_pull_on_launch(self) -> None:
        """
        Auto-pull updates on launch if enabled and repos are clean.
        
        Behavior:
          - Only runs if auto_pull is enabled
          - Skips repos with dirty worktrees
          - Runs synchronously (blocking) at startup
        """
        if not self._auto_pull:
            return
        
        print("[runner] Checking for updates...", flush=True)
        self._run_check()
        
        if self.has_updates():
            print("[runner] Updates available. Pulling...", flush=True)
            result = self.run_update(reason="auto_pull_on_launch")
            
            if result.get("success"):
                for r in result.get("results", []):
                    name = r.get("name", "?")
                    if r.get("updated"):
                        print(f"[runner] Updated: {name}", flush=True)
                    elif r.get("reason") == "dirty_worktree":
                        print(f"[runner] Skipped {name}: dirty worktree", flush=True)
            else:
                print(f"[runner] Update failed: {result.get('error', 'unknown')}", flush=True)
        else:
            print("[runner] All repos up to date.", flush=True)

    def last_update_info(self) -> dict[str, object]:
        """Get info about the last update run."""
        with self._lock:
            return {
                "at": self._last_update_at,
                "reason": self._last_update_reason,
                "results": list(self._last_update_results),
            }
