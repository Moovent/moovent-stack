"""
Unit tests for admin service startup behavior.

Goals:
- Auto-free stale listeners from previous stack runs on service start.
- Avoid killing unrelated listeners that do not belong to the service repo.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from moovent_stack.admin import services
from moovent_stack.admin.logs import LogStore
from moovent_stack.admin.services import ServiceSpec, StackManager


class _FakeProc:
    def __init__(self, pid: int = 1234) -> None:
        self.pid = pid
        self.stdout = []

    def poll(self):  # noqa: ANN201
        return None


class TestAdminServices(unittest.TestCase):
    def test_start_auto_frees_stale_listener_for_same_repo(self) -> None:
        log_store = LogStore(max_entries=50)
        manager = StackManager(log_store=log_store, quiet=True)
        spec = ServiceSpec(
            name="frontend",
            cmd=["npm", "run", "dev"],
            cwd=Path("/tmp/workspace/dashboard/client"),
            env={},
            url="http://localhost:4000",
            health_url="http://localhost:4000",
            port=4000,
            repo=None,
        )
        manager.register(spec)

        calls = {"terminate": []}
        real_tcp = services.tcp_listen_pids
        real_cmd = services.pid_command
        real_term = services.terminate_pid
        real_popen = services._popen
        try:
            seq = [[11111], []]

            def fake_tcp_listen_pids(_port: int, ttl_s: float = 2.0) -> list[int]:  # noqa: ARG001
                return seq.pop(0) if seq else []

            services.tcp_listen_pids = fake_tcp_listen_pids  # type: ignore[assignment]
            services.pid_command = lambda _pid: f"node {spec.cwd}/node_modules/.bin/vite --port 4000"  # type: ignore[assignment]
            services.terminate_pid = lambda pid, timeout_s=2.0: (calls["terminate"].append(pid) or True, "terminated")  # type: ignore[assignment]
            services._popen = lambda cmd, cwd, env: _FakeProc(22222)  # type: ignore[assignment]

            ok = manager.start("frontend")
            self.assertTrue(ok)
            self.assertEqual(calls["terminate"], [11111])
        finally:
            services.tcp_listen_pids = real_tcp  # type: ignore[assignment]
            services.pid_command = real_cmd  # type: ignore[assignment]
            services.terminate_pid = real_term  # type: ignore[assignment]
            services._popen = real_popen  # type: ignore[assignment]

    def test_start_does_not_kill_unrelated_listener(self) -> None:
        log_store = LogStore(max_entries=50)
        manager = StackManager(log_store=log_store, quiet=True)
        spec = ServiceSpec(
            name="frontend",
            cmd=["npm", "run", "dev"],
            cwd=Path("/tmp/workspace/dashboard/client"),
            env={},
            url="http://localhost:4000",
            health_url="http://localhost:4000",
            port=4000,
            repo=None,
        )
        manager.register(spec)

        calls = {"terminate": []}
        real_tcp = services.tcp_listen_pids
        real_cmd = services.pid_command
        real_term = services.terminate_pid
        real_popen = services._popen
        try:
            services.tcp_listen_pids = lambda _port, ttl_s=2.0: [33333]  # type: ignore[assignment]
            services.pid_command = lambda _pid: "python -m http.server 4000"  # type: ignore[assignment]
            services.terminate_pid = lambda pid, timeout_s=2.0: (calls["terminate"].append(pid) or True, "terminated")  # type: ignore[assignment]
            services._popen = lambda cmd, cwd, env: _FakeProc(44444)  # type: ignore[assignment]

            ok = manager.start("frontend")
            self.assertFalse(ok)
            self.assertEqual(calls["terminate"], [])
        finally:
            services.tcp_listen_pids = real_tcp  # type: ignore[assignment]
            services.pid_command = real_cmd  # type: ignore[assignment]
            services.terminate_pid = real_term  # type: ignore[assignment]
            services._popen = real_popen  # type: ignore[assignment]


if __name__ == "__main__":
    raise SystemExit(unittest.main())
