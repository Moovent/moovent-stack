"""
GitHub OAuth and API integration for the admin dashboard.

Purpose:
  OAuth flow, repo/branch fetching, connecting repos.
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .config import (
    GITHUB_OAUTH_AUTHORIZE_URL,
    GITHUB_OAUTH_TOKEN_URL,
    GITHUB_API_BASE_URL,
    GITHUB_SCOPES,
    GITHUB_REPOS_CACHE_TTL_S,
    GITHUB_BRANCHES_CACHE_TTL_S,
    load_config,
    save_config,
)
from .git_ops import git_cmd


def valid_github_full_name(value: str) -> bool:
    """Validate a GitHub repo full name (org/repo)."""
    if not value:
        return False
    return bool(re.match(r"^[\w.-]+/[\w.-]+$", value))


def github_config() -> tuple[str, str]:
    """
    Get GitHub OAuth client credentials.
    
    Returns (client_id, client_secret).
    """
    cfg = load_config()
    client_id = str(cfg.get("github_client_id", "")).strip()
    client_secret = str(cfg.get("github_client_secret", "")).strip()
    return client_id, client_secret


def save_github_config(client_id: str, client_secret: str) -> bool:
    """Save GitHub OAuth credentials."""
    cfg = load_config()
    cfg["github_client_id"] = client_id
    cfg["github_client_secret"] = client_secret
    return save_config(cfg)


def github_authorize_url(client_id: str, redirect_uri: str, state: str, scopes: str) -> str:
    """Build GitHub OAuth authorize URL."""
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
    }
    return f"{GITHUB_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


def github_exchange_code(
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
) -> tuple[bool, str, str]:
    """
    Exchange OAuth code for access token.
    
    Returns (success, access_token_or_error, token_type).
    """
    try:
        data = urlencode({
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }).encode("utf-8")
        
        req = Request(GITHUB_OAUTH_TOKEN_URL, data=data, method="POST")
        req.add_header("Accept", "application/json")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        
        with urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        
        if "error" in body:
            return False, body.get("error_description", body["error"]), ""
        
        token = body.get("access_token", "")
        token_type = body.get("token_type", "bearer")
        
        if not token:
            return False, "no_access_token", ""
        
        return True, token, token_type
    
    except HTTPError as e:
        return False, f"http_{e.code}", ""
    except Exception as e:
        return False, str(e), ""


def github_api_get(
    token: str,
    path: str,
    params: Optional[dict[str, object]] = None,
) -> tuple[bool, object, dict]:
    """
    Make a GET request to GitHub API.
    
    Returns (success, data, headers).
    """
    try:
        url = f"{GITHUB_API_BASE_URL}{path}"
        if params:
            url += "?" + urlencode(params)
        
        req = Request(url, method="GET")
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("X-GitHub-Api-Version", "2022-11-28")
        
        with urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            headers = dict(resp.headers)
            return True, data, headers
    
    except HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
            return False, body, dict(e.headers)
        except Exception:
            return False, {"error": f"http_{e.code}"}, {}
    except Exception as e:
        return False, {"error": str(e)}, {}


def github_fetch_user(token: str) -> tuple[bool, dict[str, object], str]:
    """
    Fetch authenticated user info.
    
    Returns (success, user_data, error).
    """
    ok, data, _ = github_api_get(token, "/user")
    if not ok:
        error = data.get("message", data.get("error", "unknown")) if isinstance(data, dict) else "unknown"
        return False, {}, str(error)
    return True, data if isinstance(data, dict) else {}, ""


def github_fetch_repos(token: str) -> tuple[bool, list[dict[str, object]], str]:
    """
    Fetch repos accessible to the authenticated user.
    
    Returns (success, repos, error).
    """
    repos: list[dict[str, object]] = []
    page = 1
    per_page = 100
    
    while True:
        ok, data, _ = github_api_get(token, "/user/repos", {"page": page, "per_page": per_page, "sort": "updated"})
        if not ok:
            error = data.get("message", data.get("error", "unknown")) if isinstance(data, dict) else "unknown"
            return False, [], str(error)
        
        if not isinstance(data, list):
            break
        
        repos.extend(data)
        
        if len(data) < per_page:
            break
        
        page += 1
        if page > 10:  # Safety limit
            break
    
    return True, repos, ""


def github_fetch_branches(token: str, full_name: str) -> tuple[bool, list[str]]:
    """
    Fetch branches for a repo.
    
    Returns (success, branch_names).
    """
    if not valid_github_full_name(full_name):
        return False, []
    
    branches: list[str] = []
    page = 1
    per_page = 100
    
    while True:
        ok, data, _ = github_api_get(token, f"/repos/{full_name}/branches", {"page": page, "per_page": per_page})
        if not ok:
            return False, []
        
        if not isinstance(data, list):
            break
        
        for branch in data:
            if isinstance(branch, dict) and "name" in branch:
                branches.append(branch["name"])
        
        if len(data) < per_page:
            break
        
        page += 1
        if page > 5:  # Safety limit
            break
    
    return True, branches


def git_connect_repo(repo: Path, repo_full_name: str, branch: str) -> tuple[bool, str]:
    """
    Connect a local repo to a GitHub remote and checkout branch.
    
    Returns (success, message).
    """
    if not valid_github_full_name(repo_full_name):
        return False, "invalid_repo_name"
    
    # Check if repo is a git repo
    if not (repo / ".git").exists():
        return False, "not_a_git_repo"
    
    # Set remote origin
    remote_url = f"https://github.com/{repo_full_name}.git"
    
    # Remove existing origin if present
    git_cmd(repo, ["remote", "remove", "origin"])
    
    # Add new origin
    ok, out = git_cmd(repo, ["remote", "add", "origin", remote_url])
    if not ok:
        return False, f"remote_add_failed: {out}"
    
    # Fetch
    ok, out = git_cmd(repo, ["fetch", "origin"], timeout_s=30)
    if not ok:
        return False, f"fetch_failed: {out}"
    
    # Checkout branch
    ok, out = git_cmd(repo, ["checkout", branch])
    if not ok:
        # Try creating from remote
        ok, out = git_cmd(repo, ["checkout", "-b", branch, f"origin/{branch}"])
        if not ok:
            return False, f"checkout_failed: {out}"
    
    return True, f"connected to {repo_full_name} on {branch}"


class GitHubState:
    """
    Thread-safe state for GitHub OAuth and cached data.
    
    Automatically loads saved token from config on init.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._oauth_state: Optional[str] = None
        self._access_token: Optional[str] = None
        self._user: Optional[dict[str, object]] = None
        self._repos: list[dict[str, object]] = []
        self._repos_fetched_at: float = 0
        self._branches_cache: dict[str, tuple[float, list[str]]] = {}
        
        # Load saved token from config (set by setup)
        self._load_from_config()
    
    def _load_from_config(self) -> None:
        """Load GitHub token from saved config file."""
        cfg = load_config()
        token = str(cfg.get("github_access_token", "")).strip()
        if token:
            self._access_token = token
            # Also load cached user info if available
            login = str(cfg.get("github_login", "")).strip()
            if login:
                self._user = {"login": login}

    @property
    def oauth_state(self) -> Optional[str]:
        with self._lock:
            return self._oauth_state

    @oauth_state.setter
    def oauth_state(self, value: Optional[str]) -> None:
        with self._lock:
            self._oauth_state = value

    @property
    def access_token(self) -> Optional[str]:
        with self._lock:
            return self._access_token

    @access_token.setter
    def access_token(self, value: Optional[str]) -> None:
        with self._lock:
            self._access_token = value

    @property
    def user(self) -> Optional[dict[str, object]]:
        with self._lock:
            return self._user

    @user.setter
    def user(self, value: Optional[dict[str, object]]) -> None:
        with self._lock:
            self._user = value

    def get_repos(self, token: str, force: bool = False) -> list[dict[str, object]]:
        """Get cached repos or fetch fresh."""
        now = time.time()
        with self._lock:
            if not force and self._repos and (now - self._repos_fetched_at) < GITHUB_REPOS_CACHE_TTL_S:
                return self._repos

        ok, repos, _ = github_fetch_repos(token)
        if ok:
            with self._lock:
                self._repos = repos
                self._repos_fetched_at = now
            return repos
        
        with self._lock:
            return self._repos

    def get_branches(self, token: str, full_name: str, force: bool = False) -> list[str]:
        """Get cached branches or fetch fresh."""
        now = time.time()
        with self._lock:
            if full_name in self._branches_cache and not force:
                ts, branches = self._branches_cache[full_name]
                if (now - ts) < GITHUB_BRANCHES_CACHE_TTL_S:
                    return branches

        ok, branches = github_fetch_branches(token, full_name)
        if ok:
            with self._lock:
                self._branches_cache[full_name] = (now, branches)
            return branches
        
        with self._lock:
            if full_name in self._branches_cache:
                return self._branches_cache[full_name][1]
            return []

    def clear(self) -> None:
        """Clear all cached state."""
        with self._lock:
            self._oauth_state = None
            self._access_token = None
            self._user = None
            self._repos = []
            self._repos_fetched_at = 0
            self._branches_cache.clear()
