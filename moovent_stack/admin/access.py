"""
Access control and license validation for the admin dashboard.

Purpose:
  Verify installation access, manage install IDs, cache access state.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .config import (
    ACCESS_CACHE_PATH_DEFAULT,
    ACCESS_DEFAULT_TTL_S,
    ACCESS_REQUEST_TIMEOUT_S,
    ACCESS_ENV_URL,
    ACCESS_ENV_TOKEN,
    ACCESS_ENV_TTL,
    ACCESS_ENV_SELF_CLEAN,
    ACCESS_ENV_INSTALL_ROOT,
    ACCESS_ENV_CACHE_PATH,
    env_bool,
)


def access_cache_path() -> Path:
    """Get the path to the access cache file."""
    custom = os.environ.get(ACCESS_ENV_CACHE_PATH, "").strip()
    if custom:
        return Path(custom)
    return ACCESS_CACHE_PATH_DEFAULT


def load_access_cache(path: Path) -> dict:
    """Load access cache from disk."""
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_access_cache(path: Path, data: dict) -> None:
    """Save access cache to disk."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def get_install_id(cache: dict, path: Path) -> str:
    """
    Get or create a unique install ID.
    
    The ID is tied to the cache file path to ensure consistency.
    """
    existing = cache.get("install_id", "")
    if existing and isinstance(existing, str):
        return existing
    
    # Generate new ID
    new_id = str(uuid.uuid4())
    cache["install_id"] = new_id
    save_access_cache(path, cache)
    return new_id


def access_cache_valid(cache: dict, ttl_s: float) -> bool:
    """Check if cached access is still valid."""
    if not cache.get("access_granted"):
        return False
    
    checked_at = cache.get("checked_at", 0)
    if not isinstance(checked_at, (int, float)):
        return False
    
    return (time.time() - checked_at) < ttl_s


def runner_version(workspace: Path) -> str:
    """
    Get the runner version from package metadata or fallback.
    """
    try:
        from importlib.metadata import version
        return version("moovent-stack")
    except Exception:
        pass
    
    # Fallback: check local version file
    version_file = workspace / ".moovent_stack_version"
    if version_file.exists():
        try:
            return version_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass
    
    return "unknown"


def build_access_payload(install_id: str, workspace: Path) -> dict:
    """Build the payload for access validation requests."""
    return {
        "install_id": install_id,
        "workspace": str(workspace),
        "hostname": platform.node(),
        "platform": platform.system(),
        "runner_version": runner_version(workspace),
        "timestamp": time.time(),
    }


def parse_access_response(data: dict) -> tuple[bool, str, bool]:
    """
    Parse access validation response.
    
    Returns (access_granted, message, self_clean).
    """
    access_granted = bool(data.get("access_granted", False))
    message = str(data.get("message", ""))
    self_clean = bool(data.get("self_clean", False))
    return access_granted, message, self_clean


def fetch_access_status(
    url: str,
    token: Optional[str],
    payload: dict,
) -> tuple[Optional[bool], str, bool]:
    """
    Fetch access status from remote server.
    
    Returns (access_granted_or_none, message, self_clean).
    None for access_granted means network/server error.
    """
    try:
        data = json.dumps(payload).encode("utf-8")
        req = Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        
        with urlopen(req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return parse_access_response(body)
    
    except HTTPError as e:
        if e.code == 403:
            try:
                body = json.loads(e.read().decode("utf-8"))
                return parse_access_response(body)
            except Exception:
                pass
            return False, "access_denied", False
        return None, f"http_error_{e.code}", False
    except URLError as e:
        return None, f"network_error: {e.reason}", False
    except Exception as e:
        return None, f"error: {e}", False


def parse_access_ttl() -> float:
    """Parse access TTL from environment."""
    raw = os.environ.get(ACCESS_ENV_TTL, "").strip()
    if not raw:
        return ACCESS_DEFAULT_TTL_S
    try:
        return max(60.0, float(raw))
    except ValueError:
        return ACCESS_DEFAULT_TTL_S


def safe_install_root(install_root: Path) -> bool:
    """
    Check if an install root is safe to delete.
    
    Prevents accidental deletion of system directories.
    """
    resolved = install_root.resolve()
    
    # Never delete home directory or root
    if resolved == Path.home() or resolved == Path("/"):
        return False
    
    # Must be inside home directory
    try:
        resolved.relative_to(Path.home())
    except ValueError:
        return False
    
    return True


def self_clean_install(install_root: Path, cache_path: Path) -> None:
    """
    Self-clean: remove the installation directory.
    
    Called when access is revoked and self-clean is requested.
    """
    print("[runner] Access revoked. Self-cleaning installation...", flush=True)
    
    # Remove cache file
    try:
        if cache_path.exists():
            cache_path.unlink()
    except Exception:
        pass
    
    # Remove install root if safe
    if safe_install_root(install_root):
        try:
            shutil.rmtree(install_root)
            print(f"[runner] Removed: {install_root}", flush=True)
        except Exception as e:
            print(f"[runner] Self-clean failed: {e}", flush=True)


def ensure_access_or_exit(workspace: Path) -> bool:
    """
    Verify access is granted. Returns True if access OK, False to exit.
    
    Behavior:
      1. Check if access validation is enabled (via env var)
      2. If cache is valid, return True
      3. Otherwise, fetch from server
      4. Handle self-clean if requested
    """
    access_url = os.environ.get(ACCESS_ENV_URL, "").strip()
    
    # If no access URL configured, allow (open mode)
    if not access_url:
        return True
    
    access_token = os.environ.get(ACCESS_ENV_TOKEN, "").strip() or None
    ttl_s = parse_access_ttl()
    cache_path = access_cache_path()
    cache = load_access_cache(cache_path)
    
    # Check cache first
    if access_cache_valid(cache, ttl_s):
        return True
    
    # Fetch fresh status
    install_id = get_install_id(cache, cache_path)
    payload = build_access_payload(install_id, workspace)
    
    access_granted, message, self_clean = fetch_access_status(access_url, access_token, payload)
    
    if access_granted is None:
        # Network error: allow if we had previous valid access
        if cache.get("access_granted"):
            print(f"[runner] Access check failed ({message}), using cached grant.", flush=True)
            return True
        print(f"[runner] Access check failed: {message}", flush=True)
        return False
    
    # Update cache
    cache["access_granted"] = access_granted
    cache["checked_at"] = time.time()
    cache["message"] = message
    save_access_cache(cache_path, cache)
    
    if not access_granted:
        print(f"[runner] Access denied: {message}", flush=True)
        
        # Self-clean if requested
        if self_clean and env_bool(os.environ.get(ACCESS_ENV_SELF_CLEAN)):
            install_root_str = os.environ.get(ACCESS_ENV_INSTALL_ROOT, "").strip()
            if install_root_str:
                self_clean_install(Path(install_root_str), cache_path)
        
        return False
    
    return True


def open_browser(url: str) -> None:
    """Open a URL in the default browser."""
    try:
        webbrowser.open(url)
    except Exception:
        pass
