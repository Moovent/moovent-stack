"""
Unit tests for setup server helpers.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from moovent_stack.setup import server
from moovent_stack import workspace
from moovent_stack.workspace import _default_workspace_path


class TestSetupServerWorkspaceRoot(unittest.TestCase):
    """Validate workspace root resolution logic."""

    def test_resolve_workspace_root_defaults(self) -> None:
        """Missing config should fall back to the default workspace path."""
        resolved = server._resolve_workspace_root({})
        self.assertEqual(Path(resolved), Path(_default_workspace_path()).expanduser())

    def test_resolve_workspace_root_expands_user(self) -> None:
        """Provided paths should expand ~ correctly."""
        resolved = server._resolve_workspace_root({"workspace_root": "~/Moovent-stack"})
        self.assertEqual(resolved, str(Path("~/Moovent-stack").expanduser()))


class TestWorkspaceRunnerGeneration(unittest.TestCase):
    """Validate generated runner behavior."""

    def test_generated_runner_uses_fixed_port_for_dashboard_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            workspace._ensure_workspace_runner(root)
            content = (root / "run_local_stack.py").read_text(encoding="utf-8")
            # Dashboard-only runs on port 3000 when mqtt isn't installed.
            self.assertIn('dash_port = "3000" if not mqtt_exists else "5173"', content)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
