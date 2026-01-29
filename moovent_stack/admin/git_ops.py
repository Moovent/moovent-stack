"""
Git operations for the admin dashboard.

Purpose:
  Branch switching, update detection, pull operations, repo status.
"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

from .config import GIT_CACHE_TTL_S, GIT_BRANCH_LIMIT, UPDATE_GIT_TIMEOUT_S


def git_cmd(repo: Path, args: list[str], timeout_s: float = 4.0) -> tuple[bool, str]:
    """
    Run a git command in a repo directory.
    Returns (success, output_or_error).
    """
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip() or result.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)


def git_lines(repo: Path, args: list[str]) -> list[str]:
    """Run git command and return output lines."""
    ok, out = git_cmd(repo, args)
    if not ok:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def normalize_remote_url(url: str) -> str:
    """
    Normalize git remote URLs for comparison.
    
    Examples:
      - git@github.com:org/repo.git -> github.com/org/repo
      - https://github.com/org/repo.git -> github.com/org/repo
    """
    url = url.strip()
    # SSH format
    if url.startswith("git@"):
        url = url[4:]
        url = url.replace(":", "/", 1)
    # HTTPS format
    if url.startswith("https://"):
        url = url[8:]
    if url.startswith("http://"):
        url = url[7:]
    # Remove .git suffix
    if url.endswith(".git"):
        url = url[:-4]
    # Remove trailing slashes
    url = url.rstrip("/")
    return url


def remote_web_url(remote_url: str) -> Optional[str]:
    """
    Convert a git remote URL to a web URL (GitHub only).
    Returns `None` if the remote is not recognized.
    """
    raw = (remote_url or "").strip()
    if not raw:
        return None

    norm = normalize_remote_url(raw)

    # Strip credentials in HTTPS form: user:token@github.com/org/repo
    if "@" in norm and norm.split("@", 1)[0].count("/") == 0:
        # Looks like "<creds>@github.com/org/repo"
        norm = norm.split("@", 1)[1]

    if not norm.startswith("github.com/"):
        return None

    return f"https://{norm}"


def github_commit_url(remote_url: str, commit_sha: str) -> Optional[str]:
    """Return a GitHub commit URL for a SHA, when the remote is GitHub."""
    web = remote_web_url(remote_url)
    sha = (commit_sha or "").strip()
    if not web or not sha:
        return None
    return f"{web}/commit/{sha}"


def _origin_ref(branch: str) -> str:
    return f"origin/{branch}"


def collect_git_info(repo: Path, fetch: bool = False) -> dict[str, object]:
    """
    Collect comprehensive git info for a repo.
    
    Returns dict with: branch, commit, dirty, remote_url, etc.
    """
    info: dict[str, object] = {
        "exists": repo.exists(),
        "is_git": (repo / ".git").exists(),
        "branch": None,
        "commit": None,
        "commit_short": None,
        "dirty": False,
        "remote_url": None,
        "ahead": 0,
        "behind": 0,
        "upstream_commit": None,
        "upstream_commit_short": None,
        "upstream_subject": None,
        "upstream_url": None,
        "can_update_latest": False,
        "branches_local": [],
        "branches_remote": [],
    }
    
    if not info["is_git"]:
        return info
    
    # Current branch
    ok, branch = git_cmd(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    if ok:
        info["branch"] = branch
    
    # Current commit
    ok, commit = git_cmd(repo, ["rev-parse", "HEAD"])
    if ok:
        info["commit"] = commit
        info["commit_short"] = commit[:8]
    
    # Dirty state
    ok, status = git_cmd(repo, ["status", "--porcelain"])
    if ok:
        info["dirty"] = bool(status.strip())
    
    # Remote URL
    ok, remote = git_cmd(repo, ["remote", "get-url", "origin"])
    if ok:
        info["remote_url"] = remote

    # Optional: refresh origin refs (only when explicitly forced).
    if fetch:
        git_cmd(repo, ["fetch", "--quiet", "origin"], timeout_s=UPDATE_GIT_TIMEOUT_S)
    
    # Ahead/behind + upstream latest commit
    branch = info["branch"]
    if branch and branch != "HEAD":
        origin_ref = _origin_ref(str(branch))
        ok, counts = git_cmd(repo, ["rev-list", "--left-right", "--count", f"HEAD...{origin_ref}"])
        if ok:
            parts = counts.split()
            if len(parts) == 2:
                try:
                    info["ahead"] = int(parts[0])
                    info["behind"] = int(parts[1])
                except ValueError:
                    pass

        ok, upstream_commit = git_cmd(repo, ["rev-parse", origin_ref])
        if ok and upstream_commit:
            info["upstream_commit"] = upstream_commit
            info["upstream_commit_short"] = upstream_commit[:8]
            ok, subj = git_cmd(repo, ["show", "-s", "--format=%s", origin_ref])
            if ok:
                info["upstream_subject"] = subj
            remote_url = str(info.get("remote_url") or "")
            url = github_commit_url(remote_url, upstream_commit)
            if url:
                info["upstream_url"] = url

        try:
            behind = int(info.get("behind") or 0)
        except Exception:
            behind = 0
        dirty = bool(info.get("dirty"))
        info["can_update_latest"] = bool((behind > 0) and (not dirty) and bool(info.get("upstream_commit")))
    
    # Local branches
    info["branches_local"] = git_lines(repo, ["branch", "--format=%(refname:short)"])[:GIT_BRANCH_LIMIT]
    
    # Remote branches
    remote_branches = git_lines(repo, ["branch", "-r", "--format=%(refname:short)"])
    info["branches_remote"] = [
        b.replace("origin/", "") for b in remote_branches 
        if b.startswith("origin/") and not b.endswith("/HEAD")
    ][:GIT_BRANCH_LIMIT]
    
    return info


def git_update_status(repo: Path) -> dict[str, object]:
    """
    Check if a repo has updates available.
    
    Returns dict with: has_update, behind, branch, dirty, error
    """
    result: dict[str, object] = {
        "has_update": False,
        "behind": 0,
        "branch": None,
        "dirty": False,
        "error": None,
    }
    
    if not (repo / ".git").exists():
        result["error"] = "not_a_git_repo"
        return result
    
    # Get current branch
    ok, branch = git_cmd(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    if not ok:
        result["error"] = f"branch_error: {branch}"
        return result
    result["branch"] = branch
    
    # Check dirty state
    ok, status = git_cmd(repo, ["status", "--porcelain"])
    if ok:
        result["dirty"] = bool(status.strip())
    
    # Fetch from remote (quick check)
    ok, _ = git_cmd(repo, ["fetch", "--quiet", "origin"], timeout_s=UPDATE_GIT_TIMEOUT_S)
    if not ok:
        result["error"] = "fetch_failed"
        return result
    
    # Check ahead/behind
    if branch and branch != "HEAD":
        ok, counts = git_cmd(repo, ["rev-list", "--left-right", "--count", f"HEAD...origin/{branch}"])
        if ok:
            parts = counts.split()
            if len(parts) == 2:
                try:
                    behind = int(parts[1])
                    result["behind"] = behind
                    result["has_update"] = behind > 0
                except ValueError:
                    pass
    
    return result


def git_pull_ff(repo: Path, branch: str) -> tuple[bool, str]:
    """
    Fast-forward pull a repo.
    
    Returns (success, message).
    """
    # Check dirty state first
    ok, status = git_cmd(repo, ["status", "--porcelain"])
    if ok and status.strip():
        return False, "dirty_worktree"
    
    # Pull with ff-only
    ok, out = git_cmd(repo, ["pull", "--ff-only", "origin", branch], timeout_s=UPDATE_GIT_TIMEOUT_S)
    if not ok:
        return False, out
    
    return True, out


def git_pull_latest(repo: Path) -> tuple[bool, str, str]:
    """
    Fast-forward to latest upstream commit for the current branch.

    Returns (ok, error_code_or_message, detail).

    Error codes:
    - not_a_git_repo
    - dirty_worktree
    - detached_head
    - fetch_failed
    - no_upstream
    - ff_only_failed
    - pull_failed
    """
    if not (repo / ".git").exists():
        return False, "not_a_git_repo", ""

    # Require clean worktree.
    ok, status = git_cmd(repo, ["status", "--porcelain"])
    if ok and status.strip():
        return False, "dirty_worktree", ""

    ok, branch = git_cmd(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    if not ok:
        return False, "pull_failed", branch
    if branch == "HEAD":
        return False, "detached_head", ""

    ok, _ = git_cmd(repo, ["fetch", "--quiet", "origin"], timeout_s=UPDATE_GIT_TIMEOUT_S)
    if not ok:
        return False, "fetch_failed", ""

    origin_ref = _origin_ref(branch)
    ok, _ = git_cmd(repo, ["rev-parse", origin_ref])
    if not ok:
        return False, "no_upstream", origin_ref

    ok, counts = git_cmd(repo, ["rev-list", "--left-right", "--count", f"HEAD...{origin_ref}"])
    behind = 0
    if ok:
        parts = counts.split()
        if len(parts) == 2:
            try:
                behind = int(parts[1])
            except ValueError:
                behind = 0
    if behind <= 0:
        return True, "up_to_date", ""

    ok, out = git_cmd(repo, ["pull", "--ff-only", "origin", branch], timeout_s=UPDATE_GIT_TIMEOUT_S)
    if not ok:
        msg = (out or "").lower()
        if "not possible to fast-forward" in msg or "fast-forward" in msg and "aborting" in msg:
            return False, "ff_only_failed", out
        return False, "pull_failed", out

    return True, "updated", out


def git_checkout_branch(repo: Path, branch: str) -> tuple[bool, str]:
    """
    Checkout a branch in a repo.
    
    Returns (success, message).
    """
    # Check dirty state first
    ok, status = git_cmd(repo, ["status", "--porcelain"])
    if ok and status.strip():
        return False, "dirty_worktree"
    
    # Try local branch first
    ok, out = git_cmd(repo, ["checkout", branch])
    if ok:
        return True, f"switched to {branch}"
    
    # Try remote branch
    ok, out = git_cmd(repo, ["checkout", "-b", branch, f"origin/{branch}"])
    if ok:
        return True, f"created and switched to {branch} from origin/{branch}"
    
    return False, out


class GitCache:
    """
    Thread-safe cache for git info to avoid repeated subprocess calls.
    """

    def __init__(self, ttl_s: float = GIT_CACHE_TTL_S) -> None:
        self._ttl_s = ttl_s
        self._cache: dict[str, tuple[float, dict[str, object]]] = {}
        self._lock = threading.Lock()

    def get_info(self, repo: Path, force: bool = False) -> dict[str, object]:
        key = str(repo.resolve())
        now = time.time()
        
        with self._lock:
            if key in self._cache:
                ts, info = self._cache[key]
                if not force and now - ts < self._ttl_s:
                    return info
        
        # Fetch fresh
        info = collect_git_info(repo, fetch=force)
        
        with self._lock:
            self._cache[key] = (now, info)
        
        return info

    def invalidate(self, repo: Optional[Path] = None) -> None:
        with self._lock:
            if repo:
                key = str(repo.resolve())
                self._cache.pop(key, None)
            else:
                self._cache.clear()
