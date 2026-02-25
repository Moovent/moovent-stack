"""
Unit tests for admin dependency bootstrap logic.

Goals:
- Reinstall Node deps when lockfile fingerprint changes.
- Skip Node reinstall when fingerprint matches and install is healthy.
- Reinstall Python deps when requirements fingerprint changes.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from moovent_stack.admin import deps


class TestAdminDeps(unittest.TestCase):
    def test_node_reinstalls_when_lock_fingerprint_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir) / "client"
            project.mkdir(parents=True, exist_ok=True)
            (project / "package.json").write_text('{"name":"client"}\n', encoding="utf-8")
            (project / "package-lock.json").write_text('{"lockfileVersion":3}\n', encoding="utf-8")
            (project / "node_modules").mkdir(parents=True, exist_ok=True)
            (project / ".deps_installed").write_text("lock:old\n", encoding="utf-8")

            calls: list[list[str]] = []
            real_run_cmd = deps.run_cmd
            real_vite_healthy = deps._vite_is_healthy
            try:
                deps.run_cmd = lambda cmd, cwd, env=None: calls.append(cmd)  # type: ignore[assignment]
                deps._vite_is_healthy = lambda _node_modules: True  # type: ignore[assignment]
                deps.ensure_node_deps(project)
            finally:
                deps.run_cmd = real_run_cmd  # type: ignore[assignment]
                deps._vite_is_healthy = real_vite_healthy  # type: ignore[assignment]

            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][:2], ["npm", "ci"])
            marker = (project / ".deps_installed").read_text(encoding="utf-8").strip()
            self.assertTrue(marker.startswith("lock:"))
            self.assertNotEqual(marker, "lock:old")

    def test_node_skips_install_when_fingerprint_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project = Path(tmpdir) / "client"
            project.mkdir(parents=True, exist_ok=True)
            (project / "package.json").write_text('{"name":"client"}\n', encoding="utf-8")
            lock = project / "package-lock.json"
            lock.write_text('{"lockfileVersion":3}\n', encoding="utf-8")
            (project / "node_modules").mkdir(parents=True, exist_ok=True)
            fp = f"lock:{deps._file_sha256(lock)}"
            (project / ".deps_installed").write_text(f"{fp}\n", encoding="utf-8")

            calls: list[list[str]] = []
            real_run_cmd = deps.run_cmd
            real_vite_healthy = deps._vite_is_healthy
            try:
                deps.run_cmd = lambda cmd, cwd, env=None: calls.append(cmd)  # type: ignore[assignment]
                deps._vite_is_healthy = lambda _node_modules: True  # type: ignore[assignment]
                deps.ensure_node_deps(project)
            finally:
                deps.run_cmd = real_run_cmd  # type: ignore[assignment]
                deps._vite_is_healthy = real_vite_healthy  # type: ignore[assignment]

            self.assertEqual(calls, [])

    def test_python_reinstalls_when_requirements_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "mqtt_dashboard_watch"
            repo.mkdir(parents=True, exist_ok=True)
            req = repo / "requirements.txt"
            req.write_text("requests==2.0.0\n", encoding="utf-8")
            venv_python = repo / ".venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            marker = repo / ".venv" / ".deps_installed"
            marker.write_text("req:old\n", encoding="utf-8")

            calls: list[list[str]] = []
            real_run_cmd = deps.run_cmd
            try:
                deps.run_cmd = lambda cmd, cwd, env=None: calls.append(cmd)  # type: ignore[assignment]
                py = deps.ensure_python_deps(repo, "python3")
            finally:
                deps.run_cmd = real_run_cmd  # type: ignore[assignment]

            self.assertEqual(py, str(venv_python))
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][:4], [str(venv_python), "-m", "pip", "install"])
            self.assertTrue(marker.read_text(encoding="utf-8").strip().startswith("req:"))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
