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
            # Dashboard always runs on 4000 to avoid collisions with the MQTT UI on 3000.
            self.assertIn('dash_port = "4000"', content)


class TestWorkspacePatches(unittest.TestCase):
    def test_ensure_shadcn_utils_creates_file_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "mqtt_dashboard_watch" / "mqtt-admin-dashboard" / "src").mkdir(
                parents=True, exist_ok=True
            )
            workspace._ensure_mqtt_admin_dashboard_shadcn_utils(root)
            utils_path = (
                root
                / "mqtt_dashboard_watch"
                / "mqtt-admin-dashboard"
                / "src"
                / "lib"
                / "utils.js"
            )
            self.assertTrue(utils_path.exists())
            content = utils_path.read_text(encoding="utf-8")
            self.assertIn("export function cn", content)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
