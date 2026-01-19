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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs
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

SETUP_ENV_NONINTERACTIVE = "MOOVENT_SETUP_NONINTERACTIVE"

DEFAULT_ACCESS_TTL_S = 24 * 60 * 60
ACCESS_REQUEST_TIMEOUT_S = 5.0

DEFAULT_CACHE_PATH = Path.home() / ".moovent_stack_access.json"
CONFIG_PATH = Path.home() / ".moovent_stack_config.json"


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
        # Best-effort: make file user-readable only (important for tokens).
        try:
            os.chmod(path, 0o600)
        except Exception:
            pass
    except Exception:
        return


def _load_config() -> dict:
    """Load setup config (access URL/token) from disk."""
    return _load_json(CONFIG_PATH)


def _save_config(data: dict) -> None:
    """Persist setup config to disk."""
    _save_json(CONFIG_PATH, data)


def _resolve_access_settings() -> tuple[Optional[str], Optional[str]]:
    """
    Resolve access settings.

    Priority:
    - environment variables
    - saved config file (~/.moovent_stack_config.json)
    """
    env_url = os.environ.get(ACCESS_ENV_URL, "").strip()
    env_token = os.environ.get(ACCESS_ENV_TOKEN, "").strip()
    if env_url:
        return env_url, (env_token or None)

    cfg = _load_config()
    url = str(cfg.get("access_url") or "").strip()
    token = str(cfg.get("access_token") or "").strip()
    return (url or None), (token or None)


def _setup_noninteractive() -> bool:
    """When true, do not open the setup page; fail fast instead."""
    return _env_bool(os.environ.get(SETUP_ENV_NONINTERACTIVE))


def _run_setup_server() -> tuple[str, Optional[str]]:
    """
    Launch a local setup page to collect access URL/token.

    Returns (access_url, access_token|None).
    """

    class _SetupState:
        access_url: Optional[str] = None
        access_token: Optional[str] = None
        done: bool = False

    state = _SetupState()

    html = """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Moovent Stack Setup</title>
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="bg-gray-50 text-gray-800 dark:bg-neutral-900 dark:text-neutral-200">
    <main class="min-h-screen flex items-center justify-center px-4 py-10">
      <div class="w-full max-w-xl">
        <!-- Header (auth-style) -->
        <div class="mb-6 text-center">
          <div class="mx-auto size-14 flex items-center justify-center rounded-2xl bg-white border border-gray-200 shadow-2xs dark:bg-neutral-800 dark:border-neutral-700">
            <svg class="size-7 text-indigo-600 dark:text-white" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 2a10 10 0 1 0 10 10" />
              <path d="M12 6v6l4 2" />
            </svg>
          </div>
          <h1 class="mt-4 font-semibold text-2xl text-gray-800 dark:text-neutral-200">
            Let’s get you set up
          </h1>
          <p class="mt-2 text-sm text-gray-500 dark:text-neutral-400">
            This takes less than a minute. We’ll save your settings locally so you won’t need to do this again.
          </p>
        </div>

        <!-- Card (setup-flow style) -->
        <div class="relative overflow-hidden bg-white border border-gray-200 rounded-xl shadow-2xs dark:bg-neutral-900 dark:border-neutral-700">
          <!-- Subtle gradient header (banners-style) -->
          <div class="p-5 bg-linear-to-r from-indigo-50 via-purple-50 via-70% to-sky-50 dark:from-indigo-900/30 dark:via-purple-900/30 dark:to-sky-900/30">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 class="font-semibold text-gray-800 dark:text-neutral-200">
                  Access verification
                </h2>
                <p class="mt-1 text-xs text-gray-600 dark:text-neutral-300">
                  Needed to confirm you’re allowed to use Moovent Stack.
                </p>
              </div>
              <span class="py-1 px-2 inline-flex items-center gap-x-1 text-xs font-semibold uppercase rounded-md bg-linear-to-tr from-indigo-600 to-teal-500 text-white">
                Setup
              </span>
            </div>

            <!-- Progress (setup-flow pattern) -->
            <div class="mt-4">
              <div class="flex items-center justify-between">
                <span class="text-xs text-gray-600 dark:text-neutral-300">Step 1 of 1</span>
                <span class="text-xs text-gray-600 dark:text-neutral-300">Access details</span>
              </div>
              <div class="mt-2 grid grid-cols-4 gap-x-1.5">
                <div class="bg-teal-600 h-2 flex-auto rounded-sm"></div>
                <div class="bg-teal-600 h-2 flex-auto rounded-sm"></div>
                <div class="bg-teal-600 h-2 flex-auto rounded-sm"></div>
                <div class="bg-teal-600 h-2 flex-auto rounded-sm"></div>
              </div>
            </div>
          </div>

          <!-- Form -->
          <form class="p-5 space-y-4" method="POST" action="/save">
            <div>
              <label class="block mb-2 text-sm text-gray-800 dark:text-neutral-200">
                Access URL <span class="text-red-500">*</span>
              </label>
              <input
                name="access_url"
                required
                type="url"
                placeholder="https://internal.example.com/access"
                class="py-3 px-4 block w-full border-gray-200 rounded-lg text-sm placeholder:text-gray-400 focus:border-indigo-500 focus:ring-indigo-500 disabled:opacity-50 disabled:pointer-events-none dark:bg-transparent dark:border-neutral-700 dark:text-neutral-200 dark:placeholder:text-white/60 dark:focus:ring-neutral-600"
              />
              <p class="mt-2 text-xs text-gray-500 dark:text-neutral-400">
                This endpoint tells us if your account is authorized.
              </p>
            </div>

            <div>
              <label class="block mb-2 text-sm text-gray-800 dark:text-neutral-200">
                Access Token <span class="text-xs text-gray-400">(optional)</span>
              </label>
              <input
                name="access_token"
                type="password"
                placeholder="Paste token if your access service requires it"
                class="py-3 px-4 block w-full border-gray-200 rounded-lg text-sm placeholder:text-gray-400 focus:border-indigo-500 focus:ring-indigo-500 disabled:opacity-50 disabled:pointer-events-none dark:bg-transparent dark:border-neutral-700 dark:text-neutral-200 dark:placeholder:text-white/60 dark:focus:ring-neutral-600"
              />
              <p class="mt-2 text-xs text-gray-500 dark:text-neutral-400">
                We store this locally in a config file with restricted permissions.
              </p>
            </div>

            <div class="pt-2 flex flex-col sm:flex-row gap-3">
              <button
                type="submit"
                class="py-3 px-4 w-full inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-transparent bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 disabled:pointer-events-none focus:outline-hidden focus:bg-indigo-700"
              >
                Save & Continue
                <svg class="shrink-0 size-4" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
              </button>
            </div>

            <div class="mt-3 p-3 bg-gray-50 border border-gray-200 rounded-lg dark:bg-neutral-800 dark:border-neutral-700">
              <p class="text-xs text-gray-600 dark:text-neutral-300">
                Saved locally to:
                <code class="ms-1 px-1.5 py-0.5 rounded bg-white border border-gray-200 text-gray-800 dark:bg-neutral-900 dark:border-neutral-700 dark:text-neutral-200">~/.moovent_stack_config.json</code>
              </p>
            </div>
          </form>
        </div>

        <!-- Footer (auth-style) -->
        <p class="mt-6 text-center text-xs text-gray-500 dark:text-neutral-400">
          Moovent Stack is internal. If you don’t have an Access URL, ask your team lead.
        </p>
      </div>
    </main>
  </body>
</html>
""".strip()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def _send(self, code: int, body: str, content_type: str = "text/html") -> None:
            raw = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path == "/" or self.path.startswith("/?"):
                self._send(200, html)
                return
            self._send(404, "Not found", "text/plain")

        def do_POST(self) -> None:
            if self.path != "/save":
                self._send(404, "Not found", "text/plain")
                return

            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            form = parse_qs(raw)
            access_url = (form.get("access_url", [""])[0] or "").strip()
            access_token = (form.get("access_token", [""])[0] or "").strip()
            if not access_url:
                self._send(400, "Access URL is required", "text/plain")
                return

            state.access_url = access_url
            state.access_token = access_token or None
            state.done = True

            _save_config({"access_url": state.access_url, "access_token": state.access_token or ""})

            self._send(
                200,
                """
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Saved • Moovent Stack</title>
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="bg-gray-50 text-gray-800 dark:bg-neutral-900 dark:text-neutral-200">
    <main class="min-h-screen flex items-center justify-center px-4 py-10">
      <div class="w-full max-w-md bg-white border border-gray-200 rounded-xl shadow-2xs p-6 dark:bg-neutral-900 dark:border-neutral-700">
        <div class="mx-auto size-14 flex items-center justify-center rounded-full border-2 border-emerald-500 text-emerald-500">
          <svg class="size-7" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
        </div>
        <h2 class="mt-4 text-center font-semibold text-lg text-gray-800 dark:text-neutral-200">Saved</h2>
        <p class="mt-2 text-center text-sm text-gray-500 dark:text-neutral-400">
          You can close this tab. Moovent Stack will continue automatically.
        </p>
        <div class="mt-5 flex justify-center">
          <button type="button" onclick="window.close()" class="py-2.5 px-4 inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-gray-200 bg-white text-gray-800 shadow-2xs hover:bg-gray-50 focus:outline-hidden focus:bg-gray-50 dark:bg-neutral-900 dark:border-neutral-700 dark:text-neutral-200 dark:hover:bg-neutral-800">
            Close tab
          </button>
        </div>
      </div>
    </main>
    <script>setTimeout(() => window.close(), 800);</script>
  </body>
</html>
""",
            )

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address
    setup_url = f"http://{host}:{port}/"

    print("[setup] Access is not configured. Opening setup page…")
    print(f"[setup] {setup_url}")
    _open_browser(setup_url)

    while not state.done:
        server.handle_request()

    try:
        server.server_close()
    except Exception:
        pass

    assert state.access_url is not None
    return state.access_url, state.access_token


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
    url, token = _resolve_access_settings()
    if not url:
        if _setup_noninteractive():
            raise SystemExit(f"[access] {ACCESS_ENV_URL} is required.")
        url, token = _run_setup_server()
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

