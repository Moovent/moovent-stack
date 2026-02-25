"""
Unit tests for admin watchdog change detection.

Goals:
- Detect relevant file changes per service.
- Debounce restarts to avoid restart storms.
- Preserve action type (restart vs reinstall-and-restart).
"""

from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from moovent_stack.admin.watchdog import ServiceWatchdog, WatchEvent, WatchRule


class TestAdminWatchdog(unittest.TestCase):
    def test_no_event_without_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            file_path = root / "a.txt"
            file_path.write_text("v1\n", encoding="utf-8")

            wd = ServiceWatchdog(
                [
                    WatchRule(
                        service="svc-a",
                        root=root,
                        globs=["*.txt"],
                        action="restart",
                        debounce_s=0.0,
                        reason="text changed",
                    )
                ]
            )
            wd.prime()
            self.assertEqual(wd.poll(now=time.time()), [])

    def test_event_emitted_after_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            file_path = root / "config.json"
            file_path.write_text("{\"a\":1}\n", encoding="utf-8")

            wd = ServiceWatchdog(
                [
                    WatchRule(
                        service="svc-b",
                        root=root,
                        globs=["*.json"],
                        action="restart",
                        debounce_s=0.0,
                        reason="config changed",
                    )
                ]
            )
            wd.prime()
            time.sleep(0.01)
            file_path.write_text("{\"a\":2}\n", encoding="utf-8")
            events = wd.poll(now=time.time())
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].service, "svc-b")
            self.assertEqual(events[0].action, "restart")

    def test_debounce_delays_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            file_path = root / "requirements.txt"
            file_path.write_text("a==1\n", encoding="utf-8")

            wd = ServiceWatchdog(
                [
                    WatchRule(
                        service="svc-c",
                        root=root,
                        globs=["requirements.txt"],
                        action="python_reinstall_restart",
                        debounce_s=1.0,
                        reason="python deps changed",
                    )
                ]
            )
            wd.prime()
            time.sleep(0.01)
            file_path.write_text("a==2\n", encoding="utf-8")

            t0 = time.time()
            early = wd.poll(now=t0)
            self.assertEqual(early, [])

            later = wd.poll(now=t0 + 1.1)
            self.assertEqual(len(later), 1)
            self.assertEqual(later[0], WatchEvent("svc-c", "python_reinstall_restart", "python deps changed"))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
