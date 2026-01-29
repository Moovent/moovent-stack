"""
Unit tests for admin git operations.

Goals:
- Validate "behind upstream" detection after a fetch.
- Validate fast-forward update endpoint logic (git pull --ff-only) via `git_pull_latest`.

Notes:
- These tests use the system `git` binary and temporary repositories.
- They do not touch the user's real repos.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from moovent_stack.admin.git_ops import collect_git_info, git_pull_latest, github_commit_url


def _git(cwd: Path, *args: str) -> str:
    """Run git in `cwd` and return stdout (raises on error)."""
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return (proc.stdout or "").strip()


class TestAdminGitOps(unittest.TestCase):
    def test_github_commit_url(self) -> None:
        url = github_commit_url("https://github.com/Moovent/moovent-stack.git", "abc123")
        self.assertEqual(url, "https://github.com/Moovent/moovent-stack/commit/abc123")

        url2 = github_commit_url("git@github.com:Moovent/moovent-stack.git", "deadbeef")
        self.assertEqual(url2, "https://github.com/Moovent/moovent-stack/commit/deadbeef")

        # Token-in-URL form should still parse.
        url3 = github_commit_url("https://x-access-token:token@github.com/Moovent/moovent-stack.git", "cafe")
        self.assertEqual(url3, "https://github.com/Moovent/moovent-stack/commit/cafe")

        self.assertIsNone(github_commit_url("https://gitlab.com/org/repo.git", "abc"))

    def test_collect_git_info_and_pull_latest(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bare = root / "remote.git"
            upstream = root / "upstream"
            local = root / "local"

            bare.mkdir(parents=True, exist_ok=True)
            _git(bare, "init", "--bare")

            # Upstream repo: create initial commit and push.
            upstream.mkdir(parents=True, exist_ok=True)
            _git(upstream, "init")
            _git(upstream, "config", "user.email", "test@example.com")
            _git(upstream, "config", "user.name", "Test")
            (upstream / "README.txt").write_text("v1\n", encoding="utf-8")
            _git(upstream, "add", "README.txt")
            _git(upstream, "commit", "-m", "init")
            _git(upstream, "branch", "-M", "main")
            _git(upstream, "remote", "add", "origin", str(bare))
            _git(upstream, "push", "-u", "origin", "main")

            # Clone into local repo.
            _git(root, "clone", str(bare), str(local))

            # Add another commit upstream and push, making local behind.
            (upstream / "README.txt").write_text("v2\n", encoding="utf-8")
            _git(upstream, "add", "README.txt")
            _git(upstream, "commit", "-m", "second")
            upstream_sha = _git(upstream, "rev-parse", "HEAD")
            _git(upstream, "push")

            info = collect_git_info(local, fetch=True)
            self.assertTrue(info.get("is_git"))
            self.assertEqual(info.get("branch"), "main")
            self.assertGreaterEqual(int(info.get("behind") or 0), 1)
            self.assertEqual(info.get("upstream_commit"), upstream_sha)
            self.assertTrue(bool(info.get("can_update_latest")))

            ok, code, _detail = git_pull_latest(local)
            self.assertTrue(ok)
            self.assertIn(code, ("updated", "up_to_date"))

            # After update, should not be behind.
            info2 = collect_git_info(local, fetch=True)
            self.assertEqual(int(info2.get("behind") or 0), 0)


if __name__ == "__main__":
    raise SystemExit(unittest.main())

