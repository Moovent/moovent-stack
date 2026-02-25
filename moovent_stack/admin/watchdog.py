"""
Simple file-change watchdog for stack services.

Purpose:
  Poll specific file patterns and emit debounced service restart events.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time


@dataclass(frozen=True)
class WatchRule:
    """Watch configuration for a single service."""

    service: str
    root: Path
    globs: list[str]
    action: str
    debounce_s: float
    reason: str


@dataclass(frozen=True)
class WatchEvent:
    """Emitted when a watch rule should trigger handling."""

    service: str
    action: str
    reason: str


class ServiceWatchdog:
    """
    Polling watchdog with per-rule debounce.

    Notes:
    - Uses latest mtime across watched patterns.
    - Emits at most one event per detected change burst.
    """

    def __init__(self, rules: list[WatchRule]) -> None:
        self._rules = rules
        self._last_seen: dict[int, float] = {}
        self._pending_since: dict[int, float] = {}

    def _latest_mtime(self, rule: WatchRule) -> float:
        latest = 0.0
        root = rule.root
        if not root.exists():
            return latest
        for pattern in rule.globs:
            try:
                for path in root.rglob(pattern):
                    try:
                        latest = max(latest, path.stat().st_mtime)
                    except Exception:
                        continue
            except Exception:
                continue
        return latest

    def prime(self) -> None:
        """Capture a baseline so existing files don't trigger immediately."""
        for i, rule in enumerate(self._rules):
            self._last_seen[i] = self._latest_mtime(rule)
            self._pending_since.pop(i, None)

    def poll(self, now: float | None = None) -> list[WatchEvent]:
        """Poll all rules and return triggered events."""
        t = time.time() if now is None else float(now)
        out: list[WatchEvent] = []

        for i, rule in enumerate(self._rules):
            latest = self._latest_mtime(rule)
            prev = self._last_seen.get(i, 0.0)

            if latest > prev + 1e-9:
                # First detection of this burst.
                if i not in self._pending_since:
                    self._pending_since[i] = t
                    self._last_seen[i] = latest
                else:
                    # Continue tracking latest mtime while waiting debounce.
                    self._last_seen[i] = max(self._last_seen[i], latest)

            pending_at = self._pending_since.get(i)
            if pending_at is None:
                continue
            if (t - pending_at) < max(0.0, rule.debounce_s):
                continue

            out.append(WatchEvent(rule.service, rule.action, rule.reason))
            self._pending_since.pop(i, None)

        return out
