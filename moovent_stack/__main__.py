#!/usr/bin/env python3
"""
moovent-stack: internal dev launcher (remote-only by default).

Security model:
- Secrets live on Render (or another internal environment), not on laptops.
- This CLI enforces an internal access check before doing anything.
- On revoke, it can optionally self-clean its Homebrew install on next run.
"""

from __future__ import annotations

import getpass
import json
import os
import platform
import secrets
import shutil
import socket
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen


# ----------------------------
# Config / environment knobs
# ----------------------------
ACCESS_ENV_URL = "MOOVENT_ACCESS_URL"
ACCESS_ENV_TOKEN = "MOOVENT_ACCESS_TOKEN"
ACCESS_ENV_TTL = "MOOVENT_ACCESS_TTL_S"
ACCESS_ENV_SELF_CLEAN = "MOOVENT_ACCESS_SELF_CLEAN"
ACCESS_ENV_INSTALL_ROOT = "MOOVENT_INSTALL_ROOT"
ACCESS_ENV_CACHE_PATH = "MOOVENT_ACCESS_CACHE_PATH"

REMOTE_ENV_ENABLED = "MOOVENT_REMOTE_MODE"
REMOTE_ENV_URL = "MOOVENT_REMOTE_URL"
REMOTE_ENV_BACKEND_URL = "MOOVENT_REMOTE_BACKEND_URL"
REMOTE_ENV_OPEN_BROWSER = "MOOVENT_REMOTE_OPEN_BROWSER"

DEFAULT_ACCESS_TTL_S = 24 * 60 * 60
ACCESS_REQUEST_TIMEOUT_S = 5.0

DEFAULT_CACHE_PATH = Path.home() / ".moovent_stack_access.json"


def _env_bool(value: Optional[str]) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_bool_default(value: Optional[str], default: bool) -> bool:
    if value is None or not value.strip():
        return default
    return _env_bool(value)


def _cache_path() -> Path:
    raw = os.environ.get(ACCESS_ENV_CACHE_PATH, "").strip()
    return Path(raw) if raw else DEFAULT_CACHE_PATH


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_json(path: Path, data: dict) -> None:
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        return


def _ttl_seconds() -> float:
    raw = os.environ.get(ACCESS_ENV_TTL, "").strip()
    if not raw:
        return DEFAULT_ACCESS_TTL_S
    try:
        value = float(raw)
        return value if value > 0 else DEFAULT_ACCESS_TTL_S
    except ValueError:
        return DEFAULT_ACCESS_TTL_S


def _install_id(cache: dict, path: Path) -> str:
    existing = cache.get("install_id")
    if isinstance(existing, str) and existing.strip():
        return existing
    new_id = secrets.token_hex(12)
    cache["install_id"] = new_id
    _save_json(path, cache)
    return new_id


def _cache_valid(cache: dict, ttl_s: float) -> bool:
    checked_at = cache.get("checked_at")
    if not isinstance(checked_at, (int, float)):
        return False
    return (time.time() - float(checked_at)) <= ttl_s


def _version() -> str:
    try:
        return (Path(__file__).resolve().parents[1] / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "dev"


def _payload(install_id: str) -> dict:
    return {
        "app": "moovent-stack",
        "version": _version(),
        "install_id": install_id,
        "hostname": socket.gethostname(),
        "user": getpass.getuser(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "timestamp": int(time.time()),
    }


def _parse_access_response(data: dict) -> tuple[bool, str, bool]:
    allowed = bool(data.get("allowed", data.get("allow", data.get("ok", False))))
    reason = str(data.get("reason") or data.get("message") or "")
    cleanup = bool(data.get("cleanup", data.get("revoked", data.get("revoke", False))))
    if not allowed and not cleanup:
        cleanup = True
    return allowed, reason, cleanup


def _fetch_access(url: str, token: Optional[str], payload: dict) -> tuple[Optional[bool], str, bool]:
    body = json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urlopen(req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8").strip()
            data = json.loads(raw) if raw else {}
            if isinstance(data, dict):
                return _parse_access_response(data)
            return False, "invalid_response", False
    except HTTPError as err:
        if 400 <= err.code < 500:
            return False, f"http_{err.code}", True
        return None, f"http_{err.code}", False
    except Exception as exc:
        return None, f"request_failed:{exc.__class__.__name__}", False


def _safe_install_root(install_root: Path) -> bool:
    try:
        resolved = install_root.resolve()
    except Exception:
        return False
    if str(resolved) in {"/", str(Path.home())}:
        return False
    return "Cellar" in resolved.parts


def _self_clean(install_root: Path, cache_path: Path) -> None:
    if not _safe_install_root(install_root):
        print("[access] Cleanup skipped: unsafe install root.", file=sys.stderr)
        return
    try:
        shutil.rmtree(install_root, ignore_errors=True)
    except Exception:
        pass
    for p in [cache_path]:
        try:
            if p.exists():
                p.unlink()
        except Exception:
            continue


def ensure_access_or_exit() -> None:
    url = os.environ.get(ACCESS_ENV_URL, "").strip()
    if not url:
        raise SystemExit(f"[access] {ACCESS_ENV_URL} is required.")

    token = os.environ.get(ACCESS_ENV_TOKEN, "").strip() or None
    ttl_s = _ttl_seconds()
    cache_path = _cache_path()
    cache = _load_json(cache_path)
    install_id = _install_id(cache, cache_path)

    if _cache_valid(cache, ttl_s):
        if cache.get("allowed") is True:
            return
        raise SystemExit(f"[access] Access denied (cached): {cache.get('reason', 'unknown')}")

    allowed, reason, cleanup_flag = _fetch_access(url, token, _payload(install_id))
    if allowed is None:
        if cache.get("allowed") is True:
            print("[access] Access server unreachable; using cached allow.", file=sys.stderr)
            return
        raise SystemExit("[access] Access check failed and no cached allow is available.")

    cache.update({"checked_at": time.time(), "allowed": bool(allowed), "reason": reason, "install_id": install_id})
    _save_json(cache_path, cache)

    if allowed:
        return

    print(f"[access] Access denied: {reason or 'unknown'}", file=sys.stderr)
    if _env_bool(os.environ.get(ACCESS_ENV_SELF_CLEAN)) and cleanup_flag:
        root_raw = os.environ.get(ACCESS_ENV_INSTALL_ROOT, "").strip()
        if root_raw:
            _self_clean(Path(root_raw), cache_path)
        else:
            print("[access] Cleanup skipped: install root not provided.", file=sys.stderr)
    raise SystemExit(3)


def _remote_mode_enabled() -> bool:
    return _env_bool_default(os.environ.get(REMOTE_ENV_ENABLED), True)


def _remote_url() -> str:
    url = os.environ.get(REMOTE_ENV_URL, "").strip()
    return url or "https://moovent-frontend.onrender.com"


def _remote_backend_url() -> str:
    url = os.environ.get(REMOTE_ENV_BACKEND_URL, "").strip()
    return url or "https://moovent-backend.onrender.com"


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception:
        print("[runner] Unable to open browser automatically.", file=sys.stderr)


def main() -> int:
    ensure_access_or_exit()

    if _remote_mode_enabled():
        url = _remote_url()
        api = _remote_backend_url()
        print("[runner] Remote mode: opening hosted stack (no local secrets).")
        print(f"[runner] Open: {url}")
        print(f"[runner] API:  {api}")
        if _env_bool_default(os.environ.get(REMOTE_ENV_OPEN_BROWSER), True):
            _open_browser(url)
        return 0

    print("[runner] Local mode is not implemented in this repo.", file=sys.stderr)
    print("[runner] Set MOOVENT_REMOTE_MODE=1 (default) to use Render.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

