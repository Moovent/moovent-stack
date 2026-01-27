"""
Log management for the admin dashboard.

Purpose:
  Per-service ring buffers with thread-safe access, alert detection,
  and SSE support for real-time log streaming.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

from .config import MAX_LOG_LINES


@dataclass
class LogEntry:
    """Single log line with monotonic id."""

    id: int
    ts: float
    line: str

    def to_dict(self) -> dict[str, object]:
        return {"id": self.id, "ts": self.ts, "line": self.line}


class LogStore:
    """
    Per-service ring buffer with a global id sequence.

    Edge case:
      When the buffer overflows, older ids are dropped. SSE clients can detect
      this by checking min_id vs their last seen id.
    """

    def __init__(self, max_entries: int = MAX_LOG_LINES) -> None:
        self._max_entries = max_entries
        self._entries: dict[str, deque[LogEntry]] = {}
        self._next_id = 1
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)

    def append(self, service: str, line: str) -> LogEntry:
        with self._cond:
            entry = LogEntry(id=self._next_id, ts=time.time(), line=line)
            self._next_id += 1
            buf = self._entries.setdefault(service, deque(maxlen=self._max_entries))
            buf.append(entry)
            self._cond.notify_all()
            return entry

    def tail(self, service: str, limit: int) -> list[LogEntry]:
        with self._lock:
            buf = self._entries.get(service, deque())
            if not buf:
                return []
            if limit <= 0:
                return []
            return list(buf)[-limit:]

    def since(self, service: str, after_id: int, limit: int = 200) -> list[LogEntry]:
        with self._lock:
            buf = self._entries.get(service, deque())
            if not buf:
                return []
            out = [entry for entry in buf if entry.id > after_id]
            return out[:limit]

    def min_id(self, service: str) -> Optional[int]:
        with self._lock:
            buf = self._entries.get(service, deque())
            if not buf:
                return None
            return buf[0].id

    def max_id(self, service: str) -> Optional[int]:
        with self._lock:
            buf = self._entries.get(service, deque())
            if not buf:
                return None
            return buf[-1].id

    def wait_for_new(self, service: str, after_id: int, timeout_s: float = 1.0) -> bool:
        """
        Block until new entries arrive or timeout. Returns True if new data exists.
        """
        with self._cond:
            if self._has_new(service, after_id):
                return True
            self._cond.wait(timeout_s)
            return self._has_new(service, after_id)

    def _has_new(self, service: str, after_id: int) -> bool:
        buf = self._entries.get(service, deque())
        if not buf:
            return False
        return buf[-1].id > after_id

    def detect_alert(self, service: str, lookback: int = 50) -> Optional[dict]:
        """
        Scan recent log lines for known alert patterns (e.g., port in use).
        Returns an alert dict if found, else None.

        Alert dict: {"type": str, "message": str, "ts": float}
        """
        # Patterns to detect (case-insensitive substring match)
        alert_patterns = [
            ("port_in_use", "port in use"),
            ("port_in_use", "address already in use"),
            ("port_in_use", "EADDRINUSE"),
            ("connection_refused", "connection refused"),
            ("module_not_found", "ModuleNotFoundError"),
            ("module_not_found", "Cannot find module"),
        ]
        with self._lock:
            buf = self._entries.get(service, deque())
            if not buf:
                return None
            # Check last N entries (most recent first)
            recent = list(buf)[-lookback:]
            for entry in reversed(recent):
                line_lower = entry.line.lower()
                for alert_type, pattern in alert_patterns:
                    if pattern.lower() in line_lower:
                        return {
                            "type": alert_type,
                            "message": entry.line.strip(),
                            "ts": entry.ts,
                        }
        return None

    def has_any_substring_since(
        self,
        service: str,
        *,
        since_ts: float,
        substrings: list[str],
        lookback: int = 400,
    ) -> bool:
        """
        True if any log line contains any of the provided substrings
        (case-insensitive) for entries recorded after `since_ts`.

        Purpose:
          Used to gate "STACK READY" until each service has emitted its
          expected "ready" marker line(s), to avoid printing the summary
          in the middle of startup banners.
        """
        if not substrings:
            return False
        needles = [s.lower() for s in substrings if s]
        if not needles:
            return False
        with self._lock:
            buf = self._entries.get(service, deque())
            if not buf:
                return False
            recent = list(buf)[-max(1, int(lookback)):]
            for entry in recent:
                if entry.ts < since_ts:
                    continue
                hay = entry.line.lower()
                for needle in needles:
                    if needle in hay:
                        return True
        return False
