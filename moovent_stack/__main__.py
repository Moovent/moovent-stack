#!/usr/bin/env python3
"""
moovent-stack: internal dev launcher (local-only).

Security model:
- Runs local stack from a user-provided workspace (`run_local_stack.py`).
- This CLI enforces an internal access check before doing anything.
- On revoke, it can optionally self-clean its Homebrew install on next run.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
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
INFISICAL_ENV_HOST = "INFISICAL_HOST"
INFISICAL_ENV_CLIENT_ID = "INFISICAL_CLIENT_ID"
INFISICAL_ENV_CLIENT_SECRET = "INFISICAL_CLIENT_SECRET"
INFISICAL_ENV_PROJECT_ID = "INFISICAL_PROJECT_ID"
INFISICAL_ENV_ENVIRONMENT = "INFISICAL_ENVIRONMENT"
INFISICAL_ENV_SECRET_PATH = "INFISICAL_SECRET_PATH"
GITHUB_ENV_CLIENT_ID = "MOOVENT_GITHUB_CLIENT_ID"
GITHUB_ENV_CLIENT_SECRET = "MOOVENT_GITHUB_CLIENT_SECRET"
GITHUB_ENV_ACCESS_TOKEN = "MOOVENT_GITHUB_ACCESS_TOKEN"
ACCESS_ENV_TTL = "MOOVENT_ACCESS_TTL_S"
ACCESS_ENV_SELF_CLEAN = "MOOVENT_ACCESS_SELF_CLEAN"
ACCESS_ENV_INSTALL_ROOT = "MOOVENT_INSTALL_ROOT"
ACCESS_ENV_CACHE_PATH = "MOOVENT_ACCESS_CACHE_PATH"
WORKSPACE_ENV_ROOT = "MOOVENT_WORKSPACE_ROOT"
RUNNER_ENV_PATH = "MOOVENT_RUNNER_PATH"

SETUP_ENV_NONINTERACTIVE = "MOOVENT_SETUP_NONINTERACTIVE"
SETUP_ENV_PORT = "MOOVENT_SETUP_PORT"

DEFAULT_ACCESS_TTL_S = 24 * 60 * 60
ACCESS_REQUEST_TIMEOUT_S = 5.0
DEFAULT_SETUP_PORT = 9010

DEFAULT_CACHE_PATH = Path.home() / ".moovent_stack_access.json"
CONFIG_PATH = Path.home() / ".moovent_stack_config.json"
# Default to the EU Infisical tenant for Moovent.
# Assumption: Moovent's org/project lives in EU; override via INFISICAL_HOST if needed.
DEFAULT_INFISICAL_HOST = "https://eu.infisical.com"
DEFAULT_GITHUB_SCOPES = "repo read:org"

#
# Infisical scope (org/project) enforcement
#
# Purpose:
# - Prevent users from proceeding past setup unless their Universal Auth creds can
#   access the *required* Infisical project (and therefore the correct org).
#
# Notes:
# - Today we have a single org + single project. We enforce those IDs here.
# - We validate access by listing secrets scoped to the required project ID.
# - This mirrors the mqtt_dashboard_watch integration (Universal Auth + list_secrets).
REQUIRED_INFISICAL_ORG_ID = "20256abe-9337-498a-af56-d08d6e762d29"
REQUIRED_INFISICAL_PROJECT_ID = "b33db90d-cc5b-464e-b58c-a09e7328e83d"
DEFAULT_INFISICAL_ENVIRONMENT = "dev"
DEFAULT_INFISICAL_SECRET_PATH = "/"


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


def _normalize_infisical_host(raw: Optional[str]) -> str:
    """Normalize Infisical host and ensure https:// is present."""
    value = (raw or "").strip()
    if not value:
        return DEFAULT_INFISICAL_HOST
    if value.startswith("http://") or value.startswith("https://"):
        return value.rstrip("/")
    return f"https://{value.rstrip('/')}"


def _resolve_infisical_settings() -> tuple[str, Optional[str], Optional[str]]:
    """
    Resolve Infisical Universal Auth settings.

    Priority:
    - environment variables
    - saved config file (~/.moovent_stack_config.json)
    """
    host = _normalize_infisical_host(os.environ.get(INFISICAL_ENV_HOST))
    env_client_id = os.environ.get(INFISICAL_ENV_CLIENT_ID, "").strip()
    env_client_secret = os.environ.get(INFISICAL_ENV_CLIENT_SECRET, "").strip()
    if env_client_id and env_client_secret:
        return host, env_client_id, env_client_secret

    cfg = _load_config()
    host = _normalize_infisical_host(str(cfg.get("infisical_host") or "").strip() or host)
    client_id = str(cfg.get("infisical_client_id") or "").strip()
    client_secret = str(cfg.get("infisical_client_secret") or "").strip()
    return host, (client_id or None), (client_secret or None)


def _normalize_infisical_secret_path(path: Optional[str]) -> str:
    """
    Ensure secret path is absolute to avoid accidental path mismatches.
    """
    value = (path or "").strip()
    if not value:
        return DEFAULT_INFISICAL_SECRET_PATH
    if not value.startswith("/"):
        return f"/{value}"
    return value


def _resolve_infisical_scope() -> tuple[str, str, str]:
    """
    Resolve the Infisical scope used for access validation.

    We intentionally enforce a single org + project for now.

    Returns:
    - project_id (required project UUID)
    - environment (default: dev)
    - secret_path (default: /)
    """
    # Project is fixed (single-project org).
    project_id = REQUIRED_INFISICAL_PROJECT_ID

    # Environment/path can be overridden to match your Infisical configuration.
    # This uses the same env var names as mqtt_dashboard_watch.
    cfg = _load_config()
    environment = (
        os.environ.get(INFISICAL_ENV_ENVIRONMENT)
        or str(cfg.get("infisical_environment") or "")
        or DEFAULT_INFISICAL_ENVIRONMENT
    ).strip() or DEFAULT_INFISICAL_ENVIRONMENT
    secret_path = _normalize_infisical_secret_path(
        os.environ.get(INFISICAL_ENV_SECRET_PATH)
        or str(cfg.get("infisical_secret_path") or "")
        or DEFAULT_INFISICAL_SECRET_PATH
    )
    return project_id, environment, secret_path


def _required_project_id_mismatch_reason() -> Optional[str]:
    """
    Enforce the required project ID if the user explicitly configured one.

    This avoids a footgun where a user points the stack at the wrong Infisical project
    and still passes Step 1.
    """
    cfg = _load_config()
    configured = (
        os.environ.get(INFISICAL_ENV_PROJECT_ID)
        or str(cfg.get("infisical_project_id") or "")
    ).strip()
    if configured and configured != REQUIRED_INFISICAL_PROJECT_ID:
        return "project_id_mismatch"
    return None


def _resolve_github_oauth_settings() -> tuple[Optional[str], Optional[str]]:
    """
    Resolve GitHub OAuth app credentials.

    Priority:
    - environment variables
    - saved config file (~/.moovent_stack_config.json)
    """
    env_client_id = os.environ.get(GITHUB_ENV_CLIENT_ID, "").strip()
    env_client_secret = os.environ.get(GITHUB_ENV_CLIENT_SECRET, "").strip()
    if env_client_id and env_client_secret:
        return env_client_id, env_client_secret

    cfg = _load_config()
    client_id = str(cfg.get("github_client_id") or "").strip()
    client_secret = str(cfg.get("github_client_secret") or "").strip()
    return (client_id or None), (client_secret or None)


def _resolve_github_token() -> Optional[str]:
    """Resolve stored GitHub access token."""
    env_token = os.environ.get(GITHUB_ENV_ACCESS_TOKEN, "").strip()
    if env_token:
        return env_token
    cfg = _load_config()
    token = str(cfg.get("github_access_token") or "").strip()
    return token or None


def _setup_noninteractive() -> bool:
    """When true, do not open the setup page; fail fast instead."""
    return _env_bool(os.environ.get(SETUP_ENV_NONINTERACTIVE))


def _setup_port() -> int:
    """Local setup server port (default 9010)."""
    raw = os.environ.get(SETUP_ENV_PORT, "").strip()
    if not raw:
        return DEFAULT_SETUP_PORT
    try:
        value = int(raw)
        return value if value > 0 else DEFAULT_SETUP_PORT
    except ValueError:
        return DEFAULT_SETUP_PORT


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

# Moovent brand colors (matching mqtt-admin-dashboard tailwind.config.js)
_MOOVENT_BLUE = "#A2CCF2"
_MOOVENT_TEAL = "#A6D8D4"
_MOOVENT_GREEN = "#A8DFB4"
_MOOVENT_ACCENT = "#3A8FD2"
_MOOVENT_BACKGROUND = "#FAFBFC"  # brand-background from dashboard

# Moovent logo PNG as base64 (from mqtt-admin-dashboard/public/moovent-logo.png)
# This embeds the logo directly so the setup page works offline without external deps
_MOOVENT_LOGO_BASE64 = "data:image/png;base64,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"


def _setup_steps_html(current_step: int) -> str:
    """Render the step list group (from help/tailwind set-up flows)."""
    steps = [
        "Infisical credentials",
        "GitHub + install path",
        "Repo + branch selection",
    ]
    items = []
    for idx, label in enumerate(steps, start=1):
        if idx < current_step:
            icon = (
                '<span class="size-5 flex shrink-0 justify-center items-center '
                'bg-teal-600 text-white rounded-full">'
                '<svg class="shrink-0 size-3.5" xmlns="http://www.w3.org/2000/svg" '
                'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                'stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"></path></svg>'
                "</span>"
            )
            text = f'<s class="text-sm text-gray-400">{label}</s>'
        elif idx == current_step:
            icon = (
                '<span class="size-5 flex shrink-0 justify-center items-center '
                'border border-dashed border-gray-300 text-gray-500 rounded-full">'
                f'<span class="text-[11px]">{idx}</span></span>'
            )
            text = f'<span class="text-sm text-gray-800 font-medium">{label}</span>'
        else:
            icon = (
                '<span class="size-5 flex shrink-0 justify-center items-center '
                'border border-dashed border-gray-300 text-gray-500 rounded-full">'
                f'<span class="text-[11px]">{idx}</span></span>'
            )
            text = f'<span class="text-sm text-gray-600">{label}</span>'
        items.append(
            f"""
            <div class="py-2 px-2.5 flex items-center gap-x-3 bg-gray-100 rounded-lg">
              {icon}
              <div class="grow">{text}</div>
            </div>
            """
        )
    return f'<div class="space-y-1.5">{"".join(items)}</div>'


def _setup_shell(
    step_title: str,
    step_subtitle: str,
    step_index: int,
    step_total: int,
    content_html: str,
    error_text: str = "",
) -> str:
    """Render the shared setup shell."""
    error_block = ""
    if error_text:
        error_block = f"""
        <div class="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error_text}
        </div>
        """

    progress_cells = []
    for i in range(1, step_total + 1):
        bar_class = "bg-teal-600" if i <= step_index else "bg-teal-600 opacity-30"
        progress_cells.append(f'<div class="{bar_class} h-2 flex-auto rounded-sm"></div>')

    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Moovent Stack Setup</title>
    <link rel="icon" href="{_MOOVENT_LOGO_BASE64}" />
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="text-gray-800" style="background-color: {_MOOVENT_BACKGROUND};">
    <main class="min-h-screen flex items-center justify-center px-4 py-10">
      <div class="w-full max-w-xl">
        <div class="mb-6 text-center">
          <div class="mx-auto flex items-center justify-center">
            <img src="{_MOOVENT_LOGO_BASE64}" alt="Moovent" class="h-16" />
          </div>
          <h1 class="mt-4 font-semibold text-2xl text-gray-800">Welcome to Moovent Stack</h1>
          <p class="mt-2 text-sm text-gray-500">
            Run the full Moovent development environment locally.<br/>
            Quick setup, then you're ready to code.
          </p>
        </div>

        <div class="relative overflow-hidden bg-white border border-gray-200 rounded-xl shadow-sm">
          <div class="p-5" style="background: linear-gradient(to right, {_MOOVENT_BLUE}40, {_MOOVENT_TEAL}40, {_MOOVENT_GREEN}40);">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 class="font-semibold text-gray-800">{step_title}</h2>
                <p class="mt-1 text-xs text-gray-600">{step_subtitle}</p>
              </div>
              <span class="py-1 px-2 inline-flex items-center gap-x-1 text-xs font-semibold uppercase rounded-md text-white"
                style="background: linear-gradient(to top right, {_MOOVENT_ACCENT}, #14b8a6);">
                Setup
              </span>
            </div>

            <div class="mt-4">
              <div class="flex items-center justify-between">
                <span class="text-xs text-gray-600">Step {step_index} of {step_total}</span>
                <span class="text-xs text-gray-600">{step_title}</span>
              </div>
              <div class="mt-2 grid grid-cols-{step_total} gap-x-1.5">
                {''.join(progress_cells)}
              </div>
            </div>
          </div>

          <div class="p-5 space-y-5">
            {error_block}
            {content_html}
          </div>
        </div>

        <div class="mt-4 p-4 bg-white border border-gray-200 rounded-xl">
          <h3 class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">Setup steps</h3>
          {_setup_steps_html(step_index)}
        </div>

        <p class="mt-6 text-center text-xs text-gray-500">
          Need help? Contact your team lead or check the
          <a href="https://github.com/Moovent/mqtt_dashboard_watch/blob/main/help/INSTALLATION.md" target="_blank"
            class="hover:underline" style="color: {_MOOVENT_ACCENT};">installation guide</a>.
        </p>
      </div>
    </main>
  </body>
</html>
""".strip()


def _setup_step1_html(error_text: str = "") -> str:
    """Step 1: Infisical credentials only."""
    content = f"""
    <form class="space-y-5" method="POST" action="/save-step1">
      <div>
        <label class="block mb-2 text-sm font-medium text-gray-800">
          Infisical Client ID <span class="text-red-500">*</span>
        </label>
        <input
          name="client_id"
          required
          autocomplete="username"
          placeholder="infisical_client_id_xxx"
          class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50 focus:border-[{_MOOVENT_ACCENT}]"
        />
      </div>

      <div>
        <label class="block mb-2 text-sm font-medium text-gray-800">
          Infisical Client Secret <span class="text-red-500">*</span>
        </label>
        <input
          name="client_secret"
          type="password"
          required
          autocomplete="current-password"
          placeholder="infisical_client_secret_xxx"
          class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50 focus:border-[{_MOOVENT_ACCENT}]"
        />
        <p class="mt-2 text-xs text-gray-500">
          Stored locally with restricted permissions. Default host: eu.infisical.com (set INFISICAL_HOST to override).
        </p>
      </div>

      <div class="p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <p class="text-xs text-gray-500 mb-1">Access scope</p>
        <p class="text-sm text-gray-800">
          Org: <span class="font-mono text-xs">{REQUIRED_INFISICAL_ORG_ID}</span><br/>
          Project: <span class="font-mono text-xs">{REQUIRED_INFISICAL_PROJECT_ID}</span><br/>
          Env: <span class="font-mono text-xs">{DEFAULT_INFISICAL_ENVIRONMENT}</span>
        </p>
        <p class="mt-2 text-xs text-gray-500">
          We verify your credentials can access this project before continuing.
        </p>
      </div>

      <div class="pt-2">
        <button
          type="submit"
          class="py-3 px-4 w-full inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-transparent text-white hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2"
          style="background-color: {_MOOVENT_ACCENT}; --tw-ring-color: {_MOOVENT_ACCENT};"
        >
          Continue
          <svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M12 5l7 7-7 7"/></svg>
        </button>
      </div>
    </form>
    """
    return _setup_shell(
        "Infisical access",
        "Sign in with your Infisical Universal Auth credentials",
        1,
        3,
        content,
        error_text,
    )


def _default_workspace_path() -> str:
    """Return sensible default workspace path based on OS."""
    home = Path.home()
    docs = home / "Documents" / "Moovent-stack"
    return str(docs)


def _setup_step2_html(
    github_login: Optional[str],
    error_text: str = "",
    workspace_root: str = "",
    oauth_ready: bool = True,
) -> str:
    """Step 2: GitHub OAuth + install path."""
    # Use default if not provided
    if not workspace_root:
        workspace_root = _default_workspace_path()

    status = (
        f'<span class="inline-flex items-center gap-2 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-1 rounded-md">Connected as {github_login}</span>'
        if github_login
        else '<span class="text-xs text-gray-500">Not connected yet</span>'
    )
    oauth_hint = "" if oauth_ready else "<p class='text-xs text-red-600 mt-2'>GitHub OAuth not configured. Contact your admin.</p>"

    content = f"""
    <form class="space-y-5" method="POST" action="/save-step2">
      <div>
        <label class="block mb-2 text-sm font-medium text-gray-800">
          Workspace Install Path <span class="text-red-500">*</span>
        </label>
        <input
          name="workspace_root"
          required
          autocomplete="off"
          placeholder="{_default_workspace_path()}"
          value="{workspace_root}"
          class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50 focus:border-[{_MOOVENT_ACCENT}]"
        />
        <p class="mt-2 text-xs text-gray-500">Repos will be cloned into this folder.</p>
      </div>

      <div class="p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <div class="flex items-center justify-between gap-3">
          <div>
            <p class="text-sm font-medium text-gray-800">Connect GitHub</p>
            <p class="text-xs text-gray-500">Authorize Moovent Stack to access your repos.</p>
          </div>
          <a href="/oauth/start" class="py-2 px-3 inline-flex items-center gap-x-2 text-xs font-medium rounded-lg border border-gray-200 bg-white text-gray-800 hover:bg-gray-50">
            Connect
          </a>
        </div>
        <div class="mt-2">{status}</div>
        {oauth_hint}
      </div>

      <div class="pt-2">
        <button
          type="submit"
          class="py-3 px-4 w-full inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-transparent text-white hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2"
          style="background-color: {_MOOVENT_ACCENT}; --tw-ring-color: {_MOOVENT_ACCENT};"
        >
          Continue
          <svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M12 5l7 7-7 7"/></svg>
        </button>
      </div>
    </form>
    """
    return _setup_shell(
        "GitHub + install path",
        "Authorize GitHub and choose where repos will be installed",
        2,
        3,
        content,
        error_text,
    )


def _setup_step3_html(
    mqtt_branches: list[str],
    dashboard_branches: list[str],
    error_text: str = "",
) -> str:
    """Step 3: Repo + branch selection."""
    mqtt_options = "\n".join([f"<option value='{b}'></option>" for b in mqtt_branches])
    dash_options = "\n".join([f"<option value='{b}'></option>" for b in dashboard_branches])
    content = f"""
    <form class="space-y-5" method="POST" action="/save-step3">
      <div>
        <label class="block mb-2 text-sm font-medium text-gray-800">
          mqtt_dashboard_watch branch
        </label>
        <input name="mqtt_branch" list="mqtt-branches" placeholder="main"
          class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50 focus:border-[{_MOOVENT_ACCENT}]" />
        <datalist id="mqtt-branches">{mqtt_options}</datalist>
      </div>

      <div>
        <label class="block mb-2 text-sm font-medium text-gray-800">
          dashboard branch
        </label>
        <input name="dashboard_branch" list="dashboard-branches" placeholder="main"
          class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50 focus:border-[{_MOOVENT_ACCENT}]" />
        <datalist id="dashboard-branches">{dash_options}</datalist>
      </div>

      <div class="pt-2">
        <button
          type="submit"
          class="py-3 px-4 w-full inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-transparent text-white hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2"
          style="background-color: {_MOOVENT_ACCENT}; --tw-ring-color: {_MOOVENT_ACCENT};"
        >
          Download &amp; Configure
          <svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M12 5l7 7-7 7"/></svg>
        </button>
      </div>
    </form>
    """
    return _setup_shell(
        "Repo + branches",
        "Select which branches to download",
        3,
        3,
        content,
        error_text,
    )


def _success_page_html() -> str:
    """Render the success page after saving config (light mode only)."""
    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Ready - Moovent Stack</title>
    <link rel="icon" href="{_MOOVENT_LOGO_BASE64}" />
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="text-gray-800" style="background-color: {_MOOVENT_BACKGROUND};">
    <main class="min-h-screen flex items-center justify-center px-4 py-10">
      <div class="w-full max-w-md bg-white border border-gray-200 rounded-xl shadow-sm p-6">
        <div class="mx-auto flex items-center justify-center mb-4">
          <img src="{_MOOVENT_LOGO_BASE64}" alt="Moovent" class="h-12" />
        </div>
        <div class="mx-auto w-14 h-14 flex items-center justify-center rounded-full border-2 border-emerald-500 text-emerald-500">
          <svg class="w-7 h-7" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M20 6L9 17l-5-5"/></svg>
        </div>
        <h2 class="mt-4 text-center font-semibold text-lg text-gray-800">You're all set!</h2>
        <p class="mt-2 text-center text-sm text-gray-500">
          Moovent Stack is starting. You can close this tab.
        </p>
        <div class="mt-5 flex justify-center">
          <button type="button" onclick="window.close()" class="py-2.5 px-4 inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-gray-200 bg-white text-gray-800 shadow-sm hover:bg-gray-50 focus:outline-none focus:bg-gray-50">
            Close tab
          </button>
        </div>
      </div>
    </main>
    <script>setTimeout(() => window.close(), 800);</script>
  </body>
</html>
""".strip()


def _run_setup_server() -> None:
    """
    Launch a local setup page to collect credentials + install settings.
    """

    class _SetupState:
        done: bool = False
        oauth_state: Optional[str] = None
        base_url: Optional[str] = None

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

        def _next_step(self) -> int:
            cfg = _load_config()
            if not str(cfg.get("infisical_client_id") or "").strip() or not str(
                cfg.get("infisical_client_secret") or ""
            ).strip():
                return 1
            if not str(cfg.get("workspace_root") or "").strip():
                return 2
            if not str(cfg.get("github_access_token") or "").strip():
                return 2
            return 3

        def do_GET(self) -> None:
            cfg = _load_config()
            if self.path == "/" or self.path.startswith("/?"):
                step = self._next_step()
                if step == 1:
                    self._send(200, _setup_step1_html())
                    return
                if step == 2:
                    # Try to fetch GitHub OAuth from Infisical if missing
                    _ensure_github_oauth_from_infisical()
                    cfg = _load_config()  # reload after potential update
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    oauth_ready = all(_resolve_github_oauth_settings())
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                            oauth_ready=oauth_ready,
                        ),
                    )
                    return
                token = _resolve_github_token() or ""
                mqtt_branches = _github_list_branches("Moovent", "mqtt_dashboard_watch", token) if token else []
                dash_branches = _github_list_branches("Moovent", "dashboard", token) if token else []
                self._send(200, _setup_step3_html(mqtt_branches, dash_branches))
                return

            if self.path.startswith("/oauth/start"):
                # Try to fetch GitHub OAuth from Infisical if missing
                _ensure_github_oauth_from_infisical()
                client_id, client_secret = _resolve_github_oauth_settings()
                if not client_id or not client_secret:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="GitHub OAuth Client ID/Secret is required.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                            oauth_ready=False,
                        ),
                    )
                    return
                state.oauth_state = secrets.token_urlsafe(16)
                redirect_uri = f"{state.base_url}/oauth/callback"
                auth_url = (
                    "https://github.com/login/oauth/authorize"
                    f"?client_id={client_id}"
                    f"&redirect_uri={redirect_uri}"
                    f"&scope={DEFAULT_GITHUB_SCOPES.replace(' ', '%20')}"
                    f"&state={state.oauth_state}"
                )
                self.send_response(302)
                self.send_header("Location", auth_url)
                self.end_headers()
                return

            if self.path.startswith("/oauth/callback"):
                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                params = parse_qs(query)
                code = (params.get("code", [""])[0] or "").strip()
                returned_state = (params.get("state", [""])[0] or "").strip()
                if not code or not returned_state or returned_state != state.oauth_state:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="GitHub OAuth failed. Please try again.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        ),
                    )
                    return
                client_id, client_secret = _resolve_github_oauth_settings()
                if not client_id or not client_secret:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="GitHub OAuth Client ID/Secret is required.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                            oauth_ready=False,
                        ),
                    )
                    return
                try:
                    token = _github_exchange_code(client_id, client_secret, code)
                    login = _github_get_login(token) or "GitHub user"
                    _save_config({"github_access_token": token, "github_login": login})
                    self.send_response(302)
                    self.send_header("Location", "/step2")
                    self.end_headers()
                    return
                except Exception:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="GitHub OAuth exchange failed. Please try again.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        ),
                    )
                    return

            if self.path.startswith("/step1"):
                self._send(200, _setup_step1_html())
                return

            if self.path.startswith("/step2"):
                # Try to fetch GitHub OAuth from Infisical if missing
                _ensure_github_oauth_from_infisical()
                cfg = _load_config()  # reload after potential update
                github_login = str(cfg.get("github_login") or "").strip() or None
                oauth_ready = all(_resolve_github_oauth_settings())
                self._send(
                    200,
                    _setup_step2_html(
                        github_login,
                        workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        oauth_ready=oauth_ready,
                    ),
                )
                return

            if self.path.startswith("/step3"):
                token = _resolve_github_token() or ""
                if not token:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="Connect GitHub before selecting branches.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        ),
                    )
                    return
                mqtt_branches = _github_list_branches("Moovent", "mqtt_dashboard_watch", token)
                dash_branches = _github_list_branches("Moovent", "dashboard", token)
                self._send(200, _setup_step3_html(mqtt_branches, dash_branches))
                return

            self._send(404, "Not found", "text/plain")

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            form = parse_qs(raw)

            if self.path == "/save-step1":
                client_id = (form.get("client_id", [""])[0] or "").strip()
                client_secret = (form.get("client_secret", [""])[0] or "").strip()
                if not client_id:
                    self._send(200, _setup_step1_html("Infisical Client ID is required."))
                    return
                if not client_secret:
                    self._send(200, _setup_step1_html("Infisical Client Secret is required."))
                    return

                host, _, _ = _resolve_infisical_settings()
                allowed, reason = _fetch_infisical_access(host, client_id, client_secret)
                if not allowed:
                    self._send(
                        200,
                        _setup_step1_html(
                            "Infisical access check failed. "
                            f"Reason: {reason}. "
                            "Ensure your Machine Identity has access to the required project."
                        ),
                    )
                    return

                # Fetch GitHub OAuth creds from Infisical (so user doesn't need to enter them)
                github_id, github_secret = _fetch_github_oauth_from_infisical(host, client_id, client_secret)

                config_data = {
                    "infisical_client_id": client_id,
                    "infisical_client_secret": client_secret,
                    "infisical_host": host,
                    # Persist enforced scope so other steps can reuse it.
                    "infisical_org_id": REQUIRED_INFISICAL_ORG_ID,
                    "infisical_project_id": REQUIRED_INFISICAL_PROJECT_ID,
                    "infisical_environment": DEFAULT_INFISICAL_ENVIRONMENT,
                    "infisical_secret_path": DEFAULT_INFISICAL_SECRET_PATH,
                }
                # Auto-populate GitHub OAuth if found in Infisical
                if github_id:
                    config_data["github_client_id"] = github_id
                if github_secret:
                    config_data["github_client_secret"] = github_secret

                _save_config(config_data)
                self.send_response(302)
                self.send_header("Location", "/step2")
                self.end_headers()
                return

            if self.path == "/save-step2":
                workspace_root = (form.get("workspace_root", [""])[0] or "").strip()
                if not workspace_root:
                    github_login = str(_load_config().get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="Workspace path is required.",
                            workspace_root="",
                        ),
                    )
                    return

                _save_config({"workspace_root": str(Path(workspace_root).expanduser())})

                self.send_response(302)
                self.send_header("Location", "/step3")
                self.end_headers()
                return

            if self.path == "/save-step3":
                token = _resolve_github_token()
                if not token:
                    self._send(200, _setup_step2_html(None, error_text="Connect GitHub first."))
                    return

                mqtt_branch = (form.get("mqtt_branch", ["main"])[0] or "main").strip()
                dashboard_branch = (form.get("dashboard_branch", ["main"])[0] or "main").strip()
                cfg = _load_config()
                workspace_root = str(cfg.get("workspace_root") or "").strip()
                if not workspace_root:
                    self._send(200, _setup_step2_html(None, error_text="Workspace path is required."))
                    return

                try:
                    root = Path(workspace_root).expanduser()
                    _clone_or_update_repo("Moovent", "mqtt_dashboard_watch", mqtt_branch, root / "mqtt_dashboard_watch", token)
                    _clone_or_update_repo("Moovent", "dashboard", dashboard_branch, root / "dashboard", token)

                    client_id = str(cfg.get("infisical_client_id") or "").strip()
                    client_secret = str(cfg.get("infisical_client_secret") or "").strip()
                    if client_id and client_secret:
                        _inject_infisical_env(root, client_id, client_secret)

                    _save_config(
                        {
                            "mqtt_branch": mqtt_branch,
                            "dashboard_branch": dashboard_branch,
                            "setup_complete": True,
                        }
                    )
                    state.done = True
                    self._send(200, _success_page_html())
                except Exception as exc:
                    self._send(200, _setup_step3_html([], [], f"Download failed: {exc}"))
                return

            self._send(404, "Not found", "text/plain")

    try:
        server = ThreadingHTTPServer(("127.0.0.1", _setup_port()), Handler)
    except OSError as exc:
        print(f"[setup] Unable to start local setup server: {exc}", file=sys.stderr)
        raise SystemExit(2)
    host, port = server.server_address
    setup_url = f"http://{host}:{port}/"
    state.base_url = f"http://{host}:{port}"

    print("[setup] Setup is not configured. Opening setup page…")
    print(f"[setup] {setup_url}")
    _open_browser(setup_url)

    while not state.done:
        server.handle_request()

    try:
        server.server_close()
    except Exception:
        pass


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


def _infisical_login(host: str, client_id: str, client_secret: str) -> Optional[str]:
    """
    Authenticate with Infisical Universal Auth and return access token.

    Returns:
    - access token string on success
    - None on failure
    """
    login_url = f"{host}/api/v1/auth/universal-auth/login"
    payload = {"clientId": client_id, "clientSecret": client_secret}
    body = json.dumps(payload).encode("utf-8")
    req = Request(login_url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urlopen(req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8").strip()
            data = json.loads(raw) if raw else {}
            if not isinstance(data, dict):
                return None
            token = str(
                data.get("accessToken") or data.get("token") or data.get("access_token") or ""
            ).strip()
            return token or None
    except Exception:
        return None


def _fetch_infisical_secrets(
    host: str, token: str, project_id: str, environment: str, secret_path: str
) -> dict[str, str]:
    """
    Fetch secrets from Infisical and return as dict.

    Returns:
    - dict of secret_key -> secret_value
    - empty dict on failure
    """
    from urllib.parse import urlencode

    query = urlencode(
        {
            "projectId": project_id,
            "environment": environment,
            "secretPath": secret_path,
            "expandSecretReferences": "true",
            "includeImports": "true",
            "recursive": "false",
        }
    )
    secrets_url = f"{host}/api/v4/secrets?{query}"
    secrets_req = Request(secrets_url, method="GET")
    secrets_req.add_header("Authorization", f"Bearer {token}")
    secrets_req.add_header("Accept", "application/json")

    try:
        with urlopen(secrets_req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8").strip()
            data = json.loads(raw) if raw else {}
            secrets_list = data.get("secrets", [])
            if not isinstance(secrets_list, list):
                return {}
            result = {}
            for secret in secrets_list:
                if not isinstance(secret, dict):
                    continue
                key = str(secret.get("secretKey") or secret.get("key") or "").strip()
                value = str(secret.get("secretValue") or secret.get("value") or "").strip()
                if key and value:
                    result[key] = value
            return result
    except Exception:
        return {}


def _fetch_infisical_access(host: str, client_id: str, client_secret: str) -> tuple[Optional[bool], str]:
    """
    Validate Infisical Universal Auth credentials.

    Returns:
    - allowed: True/False if request succeeded
    - allowed: None if request failed (network/server)
    - reason: failure reason for logging
    """
    project_id, environment, secret_path = _resolve_infisical_scope()
    mismatch = _required_project_id_mismatch_reason()
    if mismatch:
        return False, mismatch

    token = _infisical_login(host, client_id, client_secret)
    if not token:
        return False, "auth_failed"

    # Enforce project access by listing secrets for the required project.
    from urllib.parse import urlencode

    query = urlencode(
        {
            "projectId": project_id,
            "environment": environment,
            "secretPath": secret_path,
            "expandSecretReferences": "false",
            "includeImports": "false",
            "recursive": "false",
        }
    )
    secrets_url = f"{host}/api/v4/secrets?{query}"
    secrets_req = Request(secrets_url, method="GET")
    secrets_req.add_header("Authorization", f"Bearer {token}")
    secrets_req.add_header("Accept", "application/json")

    try:
        with urlopen(secrets_req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
            _ = resp.read()  # intentionally ignored
            return True, ""
    except HTTPError as err:
        if 400 <= err.code < 500:
            return False, f"http_{err.code}"
        return None, f"http_{err.code}"
    except Exception as exc:
        return None, f"request_failed:{exc.__class__.__name__}"


def _fetch_github_oauth_from_infisical(host: str, client_id: str, client_secret: str) -> tuple[Optional[str], Optional[str]]:
    """
    Fetch GitHub OAuth credentials from Infisical.

    Returns:
    - (github_client_id, github_client_secret) on success
    - (None, None) on failure
    """
    token = _infisical_login(host, client_id, client_secret)
    if not token:
        return None, None

    project_id, environment, secret_path = _resolve_infisical_scope()
    secrets = _fetch_infisical_secrets(host, token, project_id, environment, secret_path)

    github_id = secrets.get("MOOVENT_GITHUB_CLIENT_ID") or secrets.get("GITHUB_CLIENT_ID")
    github_secret = secrets.get("MOOVENT_GITHUB_CLIENT_SECRET") or secrets.get("GITHUB_CLIENT_SECRET")
    return github_id, github_secret


def _ensure_github_oauth_from_infisical() -> None:
    """
    Fetch GitHub OAuth from Infisical if not already in config.
    Called when Step 2 loads to handle users who completed Step 1 before this feature.
    """
    cfg = _load_config()
    # Skip if already have OAuth creds
    if cfg.get("github_client_id") and cfg.get("github_client_secret"):
        return

    # Need Infisical creds to fetch
    infisical_host = str(cfg.get("infisical_host") or "").strip()
    infisical_client_id = str(cfg.get("infisical_client_id") or "").strip()
    infisical_client_secret = str(cfg.get("infisical_client_secret") or "").strip()
    if not (infisical_host and infisical_client_id and infisical_client_secret):
        return

    github_id, github_secret = _fetch_github_oauth_from_infisical(
        infisical_host, infisical_client_id, infisical_client_secret
    )
    if github_id and github_secret:
        _save_config({"github_client_id": github_id, "github_client_secret": github_secret})


def _github_api_request(url: str, token: str) -> dict:
    """Call GitHub API with token and return JSON dict."""
    req = Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    with urlopen(req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
        raw = resp.read().decode("utf-8").strip()
        data = json.loads(raw) if raw else {}
        if not isinstance(data, dict):
            raise ValueError("invalid_response")
        return data


def _github_exchange_code(client_id: str, client_secret: str, code: str) -> str:
    """Exchange OAuth code for an access token."""
    url = "https://github.com/login/oauth/access_token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
    }
    body = json.dumps(payload).encode("utf-8")
    req = Request(url, data=body, method="POST")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    with urlopen(req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
        raw = resp.read().decode("utf-8").strip()
        data = json.loads(raw) if raw else {}
        token = str(data.get("access_token") or "").strip()
        if not token:
            raise ValueError("missing_access_token")
        return token


def _github_get_login(token: str) -> Optional[str]:
    """Fetch GitHub login for the token."""
    try:
        data = _github_api_request("https://api.github.com/user", token)
        return str(data.get("login") or "").strip() or None
    except Exception:
        return None


def _github_list_branches(owner: str, repo: str, token: str) -> list[str]:
    """List branch names for a repo."""
    url = f"https://api.github.com/repos/{owner}/{repo}/branches?per_page=100"
    req = Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    with urlopen(req, timeout=ACCESS_REQUEST_TIMEOUT_S) as resp:
        raw = resp.read().decode("utf-8").strip()
        data = json.loads(raw) if raw else []
        if not isinstance(data, list):
            return []
        return [str(item.get("name") or "").strip() for item in data if isinstance(item, dict)]


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


def _write_env_key(path: Path, key: str, value: str) -> None:
    """
    Write or update a key in a .env file.

    Preserves existing lines and comments. Appends if missing.
    """
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    updated = False
    new_lines = []
    for line in lines:
        if not line.strip() or line.lstrip().startswith("#"):
            new_lines.append(line)
            continue
        if line.split("=", 1)[0].strip() == key:
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


def _inject_infisical_env(workspace_root: Path, client_id: str, client_secret: str) -> None:
    """
    Inject Infisical creds into mqtt_dashboard_watch/.env.
    """
    env_path = workspace_root / "mqtt_dashboard_watch" / ".env"
    # Keep config aligned with mqtt_dashboard_watch Infisical loader env vars.
    # This prevents local runs failing due to missing project/environment settings.
    host, _, _ = _resolve_infisical_settings()
    project_id, environment, secret_path = _resolve_infisical_scope()
    _write_env_key(env_path, "INFISICAL_HOST", host)
    _write_env_key(env_path, "INFISICAL_PROJECT_ID", project_id)
    _write_env_key(env_path, "INFISICAL_ENVIRONMENT", environment)
    _write_env_key(env_path, "INFISICAL_SECRET_PATH", secret_path)
    _write_env_key(env_path, "INFISICAL_CLIENT_ID", client_id)
    _write_env_key(env_path, "INFISICAL_CLIENT_SECRET", client_secret)


def _run_git(cmd: list[str], cwd: Path) -> None:
    """Run git command with safe defaults."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    subprocess.check_call(cmd, cwd=str(cwd), env=env)


def _clone_or_update_repo(owner: str, repo: str, branch: str, dest: Path, token: str) -> None:
    """
    Clone or update a repo to the requested branch.

    Uses token-auth HTTPS URL for private repos.
    """
    repo_url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
    if dest.exists() and (dest / ".git").exists():
        _run_git(["git", "fetch", "origin"], dest)
        _run_git(["git", "checkout", branch], dest)
        _run_git(["git", "pull", "origin", branch], dest)
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    _run_git(["git", "clone", "--branch", branch, repo_url, str(dest)], dest.parent)


def ensure_access_or_exit(host: str, client_id: str, client_secret: str) -> None:
    ttl_s = _ttl_seconds()
    cache_path = _cache_path()
    cache = _load_json(cache_path)
    install_id = _install_id(cache, cache_path)
    project_id, _, _ = _resolve_infisical_scope()

    # Cache is only valid if:
    # - still within TTL
    # - bound to the required project (prevents stale cache across scope changes)
    if _cache_valid(cache, ttl_s) and cache.get("project_id") == project_id:
        if cache.get("allowed") is True:
            return
        raise SystemExit(f"[access] Access denied (cached): {cache.get('reason', 'unknown')}")

    allowed, reason = _fetch_infisical_access(host, client_id, client_secret)
    if allowed is None:
        if cache.get("allowed") is True:
            print("[access] Infisical unreachable; using cached allow.", file=sys.stderr)
            return
        raise SystemExit("[access] Infisical auth failed and no cached allow is available.")

    cache.update(
        {
            "checked_at": time.time(),
            "allowed": bool(allowed),
            "reason": reason,
            "install_id": install_id,
            "project_id": project_id,
        }
    )
    _save_json(cache_path, cache)

    if allowed:
        return

    print(f"[access] Access denied: {reason or 'invalid_credentials'}", file=sys.stderr)
    if _env_bool(os.environ.get(ACCESS_ENV_SELF_CLEAN)):
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
    host, client_id, client_secret = _resolve_infisical_settings()
    runner_path = _resolve_runner_path()

    if not client_id or not client_secret or not runner_path:
        if _setup_noninteractive():
            print("[runner] Missing setup. Provide Infisical credentials and workspace path.", file=sys.stderr)
            return 2
        _run_setup_server()
        host, client_id, client_secret = _resolve_infisical_settings()
        runner_path = _resolve_runner_path()
        if not client_id or not client_secret or not runner_path:
            print("[runner] Setup incomplete. Please finish setup.", file=sys.stderr)
            return 2

    ok, error = _validate_runner_path(runner_path)
    if not ok:
        print(f"[runner] {error}", file=sys.stderr)
        return 2

    # Authenticate via Infisical Universal Auth before running the stack.
    ensure_access_or_exit(host, client_id, client_secret)
    return _run_local_stack(runner_path)


if __name__ == "__main__":
    raise SystemExit(main())
