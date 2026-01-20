#!/usr/bin/env python3
"""
moovent-stack: internal dev launcher (local-only).

Security model:
- Runs local stack from a user-provided workspace (`run_local_stack.py`).
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
import subprocess
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
WORKSPACE_ENV_ROOT = "MOOVENT_WORKSPACE_ROOT"
RUNNER_ENV_PATH = "MOOVENT_RUNNER_PATH"

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
    current = _load_config()
    current.update(data)
    _save_json(CONFIG_PATH, current)


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


def _resolve_runner_path() -> Optional[Path]:
    """Resolve the path to run_local_stack.py."""
    raw_runner = os.environ.get(RUNNER_ENV_PATH, "").strip()
    if raw_runner:
        return Path(raw_runner).expanduser()

    raw_root = os.environ.get(WORKSPACE_ENV_ROOT, "").strip()
    if raw_root:
        return (Path(raw_root).expanduser() / "run_local_stack.py")

    cfg = _load_config()
    root = str(cfg.get("workspace_root") or "").strip()
    if root:
        return (Path(root).expanduser() / "run_local_stack.py")

    return None


def _validate_runner_path(path: Path) -> tuple[bool, str]:
    """Validate workspace layout for local stack."""
    if not path.exists():
        return False, f"run_local_stack.py not found at: {path}"
    root = path.parent
    missing = []
    if not (root / "mqtt_dashboard_watch").exists():
        missing.append("mqtt_dashboard_watch/")
    if not (root / "dashboard").exists():
        missing.append("dashboard/")
    if missing:
        return False, f"Workspace missing: {', '.join(missing)} (expected under {root})"
    return True, ""


# ---------------------------------------------------------------------------
# HTML Templates for setup UI
# ---------------------------------------------------------------------------

# Moovent brand colors used in gradients
_MOOVENT_BLUE = "#A2CCF2"
_MOOVENT_TEAL = "#A6D8D4"
_MOOVENT_GREEN = "#A8DFB4"
_MOOVENT_ACCENT = "#3A8FD2"

# Inline Moovent logo SVG (infinity-like MQTT symbol)
_MOOVENT_LOGO_SVG = """
<svg width="100%" height="100%" viewBox="0 0 200 100" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="brandGradient" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" style="stop-color:#A2CCF2;stop-opacity:1" />
      <stop offset="50%" style="stop-color:#A6D8D4;stop-opacity:1" />
      <stop offset="100%" style="stop-color:#A8DFB4;stop-opacity:1" />
    </linearGradient>
  </defs>
  <path 
    d="M 50 25 C 30 25, 10 35, 10 50 C 10 65, 30 75, 50 75 C 60 75, 70 72, 77 67 L 100 50 L 123 33 C 130 28, 140 25, 150 25 C 170 25, 190 35, 190 50 C 190 65, 170 75, 150 75 C 130 75, 110 65, 110 50 C 110 35, 130 25, 150 25"
    fill="none" stroke="url(#brandGradient)" stroke-width="6" stroke-linecap="round"
  />
  <circle cx="65" cy="35" r="4" fill="#3A8FD2"/>
</svg>
""".strip()


def _setup_page_html(error_text: str = "") -> str:
    """
    Render the setup page HTML with Moovent branding.

    Includes:
    - Moovent logo at the top
    - Clear explanations for each field (Access URL, Access Token, Workspace)
    - Moovent brand colors in gradients and accents
    """
    error_block = ""
    if error_text:
        error_block = f"""
        <div class="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error_text}
        </div>
        """

    return f"""
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
        <!-- Header with Moovent logo -->
        <div class="mb-6 text-center">
          <div class="mx-auto w-24 h-12 flex items-center justify-center">
            {_MOOVENT_LOGO_SVG}
          </div>
          <h1 class="mt-4 font-semibold text-2xl text-gray-800 dark:text-neutral-200">
            Welcome to Moovent Stack
          </h1>
          <p class="mt-2 text-sm text-gray-500 dark:text-neutral-400">
            Run the full Moovent development environment locally.<br/>
            Quick setup, then you're ready to code.
          </p>
        </div>

        <!-- Card -->
        <div class="relative overflow-hidden bg-white border border-gray-200 rounded-xl shadow-sm dark:bg-neutral-900 dark:border-neutral-700">
          <!-- Gradient header with Moovent colors -->
          <div class="p-5 bg-gradient-to-r from-[{_MOOVENT_BLUE}]/30 via-[{_MOOVENT_TEAL}]/30 to-[{_MOOVENT_GREEN}]/30 dark:from-[{_MOOVENT_BLUE}]/20 dark:via-[{_MOOVENT_TEAL}]/20 dark:to-[{_MOOVENT_GREEN}]/20">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 class="font-semibold text-gray-800 dark:text-neutral-200">
                  Developer Access
                </h2>
                <p class="mt-1 text-xs text-gray-600 dark:text-neutral-300">
                  Connect to Moovent's internal services
                </p>
              </div>
              <span class="py-1 px-2 inline-flex items-center gap-x-1 text-xs font-semibold uppercase rounded-md bg-gradient-to-tr from-[{_MOOVENT_ACCENT}] to-teal-500 text-white">
                Setup
              </span>
            </div>
          </div>

          <!-- Form -->
          <form class="p-5 space-y-5" method="POST" action="/save">
            {error_block}

            <!-- Access URL field with explanation -->
            <div>
              <label class="block mb-2 text-sm font-medium text-gray-800 dark:text-neutral-200">
                Access URL <span class="text-red-500">*</span>
              </label>
              <input
                name="access_url"
                required
                type="url"
                placeholder="https://access.moovent.io/verify"
                class="py-3 px-4 block w-full border border-gray-200 rounded-lg text-sm placeholder:text-gray-400 focus:border-[{_MOOVENT_ACCENT}] focus:ring-[{_MOOVENT_ACCENT}] dark:bg-transparent dark:border-neutral-700 dark:text-neutral-200 dark:placeholder:text-white/60"
              />
              <div class="mt-2 p-2.5 bg-gray-50 border border-gray-100 rounded-lg dark:bg-neutral-800 dark:border-neutral-700">
                <p class="text-xs text-gray-600 dark:text-neutral-400">
                  <strong class="text-gray-700 dark:text-neutral-300">What is this?</strong>
                  The Access URL is Moovent's internal endpoint that verifies you're an authorized developer. 
                  Your team lead will provide this URL when onboarding you.
                </p>
              </div>
            </div>

            <!-- Access Token field with explanation -->
            <div>
              <label class="block mb-2 text-sm font-medium text-gray-800 dark:text-neutral-200">
                Access Token <span class="text-xs text-gray-400 font-normal">(if required)</span>
              </label>
              <input
                name="access_token"
                type="password"
                placeholder="moo_dev_xxxxxxxxxxxx"
                class="py-3 px-4 block w-full border border-gray-200 rounded-lg text-sm placeholder:text-gray-400 focus:border-[{_MOOVENT_ACCENT}] focus:ring-[{_MOOVENT_ACCENT}] dark:bg-transparent dark:border-neutral-700 dark:text-neutral-200 dark:placeholder:text-white/60"
              />
              <div class="mt-2 p-2.5 bg-gray-50 border border-gray-100 rounded-lg dark:bg-neutral-800 dark:border-neutral-700">
                <p class="text-xs text-gray-600 dark:text-neutral-400">
                  <strong class="text-gray-700 dark:text-neutral-300">What is this?</strong>
                  A personal token that authenticates you to the access service. 
                  Some team configurations require it, others don't. Check with your team lead if unsure.
                  <span class="block mt-1 text-gray-500 dark:text-neutral-500">Stored locally with restricted permissions (only you can read it).</span>
                </p>
              </div>
            </div>

            <!-- Workspace Folder field -->
            <div>
              <label class="block mb-2 text-sm font-medium text-gray-800 dark:text-neutral-200">
                Workspace Folder <span class="text-red-500">*</span>
              </label>
              <input
                name="workspace_root"
                required
                placeholder="/Users/you/Projects/moovent"
                class="py-3 px-4 block w-full border border-gray-200 rounded-lg text-sm placeholder:text-gray-400 focus:border-[{_MOOVENT_ACCENT}] focus:ring-[{_MOOVENT_ACCENT}] dark:bg-transparent dark:border-neutral-700 dark:text-neutral-200 dark:placeholder:text-white/60"
              />
              <div class="mt-2 p-2.5 bg-gray-50 border border-gray-100 rounded-lg dark:bg-neutral-800 dark:border-neutral-700">
                <p class="text-xs text-gray-600 dark:text-neutral-400">
                  <strong class="text-gray-700 dark:text-neutral-300">What is this?</strong>
                  The folder where you cloned the Moovent repos. It must contain:
                </p>
                <ul class="mt-1.5 text-xs text-gray-600 dark:text-neutral-400 space-y-0.5">
                  <li class="flex items-center gap-1.5">
                    <svg class="size-3 text-[{_MOOVENT_ACCENT}]" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>
                    <code class="px-1 py-0.5 bg-white border border-gray-200 rounded text-gray-700 dark:bg-neutral-900 dark:border-neutral-600 dark:text-neutral-300">mqtt_dashboard_watch/</code>
                    <span class="text-gray-500">(backend)</span>
                  </li>
                  <li class="flex items-center gap-1.5">
                    <svg class="size-3 text-[{_MOOVENT_ACCENT}]" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>
                    <code class="px-1 py-0.5 bg-white border border-gray-200 rounded text-gray-700 dark:bg-neutral-900 dark:border-neutral-600 dark:text-neutral-300">dashboard/</code>
                    <span class="text-gray-500">(frontend)</span>
                  </li>
                  <li class="flex items-center gap-1.5">
                    <svg class="size-3 text-[{_MOOVENT_ACCENT}]" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                    <code class="px-1 py-0.5 bg-white border border-gray-200 rounded text-gray-700 dark:bg-neutral-900 dark:border-neutral-600 dark:text-neutral-300">run_local_stack.py</code>
                    <span class="text-gray-500">(launcher script)</span>
                  </li>
                </ul>
              </div>
            </div>

            <div class="pt-2">
              <button
                type="submit"
                class="py-3 px-4 w-full inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-transparent bg-[{_MOOVENT_ACCENT}] text-white hover:bg-[{_MOOVENT_ACCENT}]/90 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50"
              >
                Save &amp; Start Moovent Stack
                <svg class="shrink-0 size-4" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
              </button>
            </div>

            <div class="p-3 bg-gray-50 border border-gray-200 rounded-lg dark:bg-neutral-800 dark:border-neutral-700">
              <p class="text-xs text-gray-600 dark:text-neutral-300 flex items-center gap-1.5">
                <svg class="size-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/></svg>
                Settings saved locally to
                <code class="px-1.5 py-0.5 rounded bg-white border border-gray-200 text-gray-700 dark:bg-neutral-900 dark:border-neutral-700 dark:text-neutral-200">~/.moovent_stack_config.json</code>
              </p>
            </div>
          </form>
        </div>

        <!-- Footer -->
        <p class="mt-6 text-center text-xs text-gray-500 dark:text-neutral-400">
          Need help? Contact your team lead or check the
          <a href="https://github.com/Moovent/mqtt_dashboard_watch/blob/main/help/INSTALLATION.md" target="_blank" class="text-[{_MOOVENT_ACCENT}] hover:underline">installation guide</a>.
        </p>
      </div>
    </main>
  </body>
</html>
""".strip()


def _success_page_html() -> str:
    """Render the success page after saving config."""
    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Ready - Moovent Stack</title>
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="bg-gray-50 text-gray-800 dark:bg-neutral-900 dark:text-neutral-200">
    <main class="min-h-screen flex items-center justify-center px-4 py-10">
      <div class="w-full max-w-md bg-white border border-gray-200 rounded-xl shadow-sm p-6 dark:bg-neutral-900 dark:border-neutral-700">
        <div class="mx-auto w-20 h-10 flex items-center justify-center mb-2">
          {_MOOVENT_LOGO_SVG}
        </div>
        <div class="mx-auto size-14 flex items-center justify-center rounded-full border-2 border-emerald-500 text-emerald-500">
          <svg class="size-7" xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>
        </div>
        <h2 class="mt-4 text-center font-semibold text-lg text-gray-800 dark:text-neutral-200">You're all set!</h2>
        <p class="mt-2 text-center text-sm text-gray-500 dark:text-neutral-400">
          Moovent Stack is starting. You can close this tab.
        </p>
        <div class="mt-5 flex justify-center">
          <button type="button" onclick="window.close()" class="py-2.5 px-4 inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-gray-200 bg-white text-gray-800 shadow-sm hover:bg-gray-50 focus:outline-none focus:bg-gray-50 dark:bg-neutral-900 dark:border-neutral-700 dark:text-neutral-200 dark:hover:bg-neutral-800">
            Close tab
          </button>
        </div>
      </div>
    </main>
    <script>setTimeout(() => window.close(), 800);</script>
  </body>
</html>
""".strip()


def _run_setup_server() -> tuple[str, Optional[str], Path]:
    """
    Launch a local setup page to collect access URL/token.

    Returns (access_url, access_token|None, runner_path).
    """

    class _SetupState:
        access_url: Optional[str] = None
        access_token: Optional[str] = None
        done: bool = False

    state = _SetupState()

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
                self._send(200, _setup_page_html())
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
            workspace_root = (form.get("workspace_root", [""])[0] or "").strip()

            if not access_url:
                self._send(200, _setup_page_html("Access URL is required."))
                return
            if not workspace_root:
                self._send(200, _setup_page_html("Workspace folder is required."))
                return

            runner_path = Path(workspace_root).expanduser() / "run_local_stack.py"
            ok, error = _validate_runner_path(runner_path)
            if not ok:
                self._send(200, _setup_page_html(error))
                return

            state.access_url = access_url
            state.access_token = access_token or None
            state.done = True

            _save_config(
                {
                    "access_url": state.access_url,
                    "access_token": state.access_token or "",
                    "workspace_root": str(Path(workspace_root).expanduser()),
                }
            )

            self._send(200, _success_page_html())

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
    runner_path = _resolve_runner_path()
    assert runner_path is not None
    return state.access_url, state.access_token, runner_path


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


def ensure_access_or_exit(url: str, token: Optional[str]) -> None:
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


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception:
        print("[runner] Unable to open browser automatically.", file=sys.stderr)


def _run_local_stack(runner_path: Path) -> int:
    """Run the local stack via run_local_stack.py."""
    print("[runner] Starting local stack...")
    return subprocess.call([sys.executable, str(runner_path)])


def main() -> int:
    access_url, access_token = _resolve_access_settings()
    runner_path = _resolve_runner_path()

    if not access_url or not runner_path:
        if _setup_noninteractive():
            print("[runner] Missing setup. Provide access URL and workspace path.", file=sys.stderr)
            return 2
        access_url, access_token, runner_path = _run_setup_server()

    ok, error = _validate_runner_path(runner_path)
    if not ok:
        print(f"[runner] {error}", file=sys.stderr)
        return 2

    ensure_access_or_exit(access_url, access_token)
    return _run_local_stack(runner_path)


if __name__ == "__main__":
    raise SystemExit(main())
