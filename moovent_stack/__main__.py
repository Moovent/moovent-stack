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

# Moovent brand colors (matching mqtt-admin-dashboard tailwind.config.js)
_MOOVENT_BLUE = "#A2CCF2"
_MOOVENT_TEAL = "#A6D8D4"
_MOOVENT_GREEN = "#A8DFB4"
_MOOVENT_ACCENT = "#3A8FD2"
_MOOVENT_BACKGROUND = "#FAFBFC"  # brand-background from dashboard

# Moovent logo PNG as base64 (from mqtt-admin-dashboard/public/moovent-logo.png)
# This embeds the logo directly so the setup page works offline without external deps
_MOOVENT_LOGO_BASE64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAABdwAAAGoCAYAAABcySegAAAAAXNSR0IArs4c6QAAAIRlWElmTU0AKgAAAAgABQESAAMAAAABAAEAAAEaAAUAAAABAAAASgEbAAUAAAABAAAAUgEoAAMAAAABAAIAAIdpAAQAAAABAAAAWgAAAAAAAAEsAAAAAQAAASwAAAABAAOgAQADAAAAAQABAACgAgAEAAAAAQAABdygAwAEAAAAAQAAAagAAAAA3E9bAAAAAAlwSFlzAAAuIwAALiMBeKU/dgAAAVlpVFh0WE1MOmNvbS5hZG9iZS54bXAAAAAAADx4OnhtcG1ldGEgeG1sbnM6eD0iYWRvYmU6bnM6bWV0YS8iIHg6eG1wdGs9IlhNUCBDb3JlIDYuMC4wIj4KICAgPHJkZjpSREYgeG1sbnM6cmRmPSJodHRwOi8vd3d3LnczLm9yZy8xOTk5LzAyLzIyLXJkZi1zeW50YXgtbnMjIj4KICAgICAgPHJkZjpEZXNjcmlwdGlvbiByZGY6YWJvdXQ9IiIKICAgICAgICAgICAgeG1sbnM6dGlmZj0iaHR0cDovL25zLmFkb2JlLmNvbS90aWZmLzEuMC8iPgogICAgICAgICA8dGlmZjpPcmllbnRhdGlvbj4xPC90aWZmOk9yaWVudGF0aW9uPgogICAgICA8L3JkZjpEZXNjcmlwdGlvbj4KICAgPC9yZGY6UkRGPgo8L3g6eG1wbWV0YT4KGV7hBwAAQABJREFUeAHsnQeAHkd99ufae70XnaST7iSdekOWO7aRKxibjugkBBJDIB8kgRDqF9ETkpCEDwIkhtCLRQnVuGG5Icu2LDfJsupJOrXrvZfveWZ33tu3XZFO0pVnpP9tm52d+U3Z3WfmnTVGTgREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQAREQARmKIGkGZouJUsEREAEREAEREAEREAEREAEREAEREAEREAEREAEpioB6rIzTZsdRppos9rNtEyd1ZmpxIuACIiACIiACIiACIiACIiACIiACIiACIiACEwLAjNRl531Yvu0KHmKpAiIgAiIgAiIgAiIgAiIgAiIgAiIgAiIgAiIgAiIwLQgMBM7EiYEftYDmBAteRYBERABERABERABERABERABERABERABERABERCBMyXAX3iwAyrV74SiuJ5Q7N64aVMJOqxKUL7ntzc0lKRlZy9oqa/Pz83PL+/t7i7qaG3NzCspKR4eHMztausI9XZ1JIWystLTMzMzUUX8OsLHumGDKpI0ODg40NXS0pkSCg1l5eYOpmdkdsM19vd0txeWlXV1dXQcD6Wnt2RmZ5/u6e09WVRYWDc0NHRyw/LljVu3bk30YEwRPs1UVCStzs8f3L17N+tI3HqP/XIiIAIiIAIiIAIiIAIiIAIiIAIiIAIiIAIiIAKxBJwWy2d4Ce6xfGbEHpfJMyIxSoQIiIAIiIAIiIAIiIAIiIAIiIAIiIAIiIAIiMA5I5CEEeypp0+fTq31BPZeXCkshPOqW7ZsSd56768rOltaF/f19FT39vQvGR4aXNzfO1ABIW/uwEB/EUaq5w/2Q6NLSjIDvf0Gg9XN0BCCcXrhWUYfwrsNAXqjSQmlmeGhIZMaSuvBdlNKKLU+OSn5eFoo7WhKcsr+1KyMA1kZmQcrlpUd2bZ1W0ucS1OAT8Xo3sEDbzvQj6loJCzGgaRdAQIYwV69a1fqgQMHKExTjI4R2C+7+ea85lOnFrW3tS0e6O1dNjg8iPrSV4mSOw/1pjQ5JaWor7s7lJKaavp7Wc08x7I8GY51g/WPdS4lLc0kJdup3IfRUdWKXY2podBJ1JNaLA+mpacdDKVm7i8szjv89Pbtx+NcnyenV1RUmDlz5gxgBPy4RuvHCUe7REAEREAEREAEREAERGC2EPBeWr33aQnuMzTXXSbP0OQpWSIgAiIgAiIgAiIgAiIgAiIgAiIgAiIgAiIgAudBIAlic8gXDymkRYhpm169qaD26OkVna1t6/u6+9b29fevGhwYXDTY318+2D+YQYFwaGAoOEA9GBWqh86ccO+W1h/Ec96jaG6/W0+yI3qHw/utf/8P/VAEpOAZd/5rivzWUlOGIGrWp6alHoMovy+UnvZcWih0VEF52XPPPfj4MT88t2C4GRQWr7jiij6MANb0M47MLF/yOwWoI2noiCKJmJHhyy65ZHF3W/Pa7q7edYP9fWv7+weqUUcWDPT1lQwNDhraKGI6y5mrJwzf1QWuUzi3ztuwx8J1hBXP1hP/YGBBP8F6wvUIRxGelpKSapJT0zpT0lJPpqWlHUoLpe9JSU9/Nic78+klc1+09+67v9cZcaI3Hzy/2zCA0e9sLyLjG+VZmyIgAiIgAiIgAiIgAiIwCwm4528+K0twn6EFwGXyDE2ekiUCIiACIiACIiACIiACIiACIiACIiACIiACBywBv2w/QgROlQ6pSJys62skXrDzzXbkP4p+tcJYXraPOeQYAiEwJYEsHlMCS/IQCIEQCIEQCIEQCIEQCIEQCIEQCIEQCIF9msBBat1uaa30Q+kp6Q6Jb7evlNZJh0k24nn5jl02PuUYAiEQAiEQAiEQAiEQAiEQAiEQAiEQAiEQAiEQAiEQAiHgP4h6oVD4Z2Lqc/kzMrsm6b41QZcvqMaHQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQkAE+COp2AaJF+38XMx/JmFetBPm/G/pGYk0d0r+6Rn/JI2iYiEQAiEwHYH8i910vJI6BEIgBEIgBEIgBEIgBEIgBEIgBEIgBEJg3yXAy3JeqGP+46fl77Tz8zGk4cyLeXSrdIH0rMQfV+VlfCwEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAEDmgC5bfTLxYJf4O9/kkZru+SPiP5C6llXkXHQiAEQmB6AvxrXiwEQiAEQiAEQiAEQiAEQiAEQiAEQiAEQiAE9hcC5R9BPVydWiO9QjpY4t4/pK3SvRI/N4Pxsp1vwsdCIARCIARCIARCIARCIARCIARCIARCIARCIARCIARCIARmJJAvpM4ILtlCIAQWE8iCsphJYkIgBEIgBEIgBEIgBEIgBEIgBEIgBEIgBJY/gfK9VxmmZ/ykjK0MOy7nEAiBEJiJwP8Ap5WLjkKLfL4AAAAASUVORK5CYII="


def _setup_page_html(error_text: str = "") -> str:
    """
    Render the setup page HTML with Moovent branding (light mode only).
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
  <body class="text-gray-800" style="background-color: {_MOOVENT_BACKGROUND};">
    <main class="min-h-screen flex items-center justify-center px-4 py-10">
      <div class="w-full max-w-xl">
        <!-- Header with Moovent logo -->
        <div class="mb-6 text-center">
          <div class="mx-auto flex items-center justify-center">
            <img src="{_MOOVENT_LOGO_BASE64}" alt="Moovent" class="h-16" />
          </div>
          <h1 class="mt-4 font-semibold text-2xl text-gray-800">
            Welcome to Moovent Stack
          </h1>
          <p class="mt-2 text-sm text-gray-500">
            Run the full Moovent development environment locally.<br/>
            Quick setup, then you're ready to code.
          </p>
        </div>

        <!-- Card -->
        <div class="relative overflow-hidden bg-white border border-gray-200 rounded-xl shadow-sm">
          <!-- Gradient header with Moovent colors -->
          <div class="p-5" style="background: linear-gradient(to right, {_MOOVENT_BLUE}40, {_MOOVENT_TEAL}40, {_MOOVENT_GREEN}40);">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 class="font-semibold text-gray-800">
                  Developer Access
                </h2>
                <p class="mt-1 text-xs text-gray-600">
                  Connect to Moovent's internal services
                </p>
              </div>
              <span class="py-1 px-2 inline-flex items-center gap-x-1 text-xs font-semibold uppercase rounded-md text-white" style="background: linear-gradient(to top right, {_MOOVENT_ACCENT}, #14b8a6);">
                Setup
              </span>
            </div>
          </div>

          <!-- Form -->
          <form class="p-5 space-y-5" method="POST" action="/save">
            {error_block}

            <!-- Access URL field -->
            <div>
              <label class="block mb-2 text-sm font-medium text-gray-800">
                Access URL <span class="text-red-500">*</span>
              </label>
              <input
                name="access_url"
                required
                type="url"
                autocomplete="url"
                placeholder="https://access.moovent.io/verify"
                class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50 focus:border-[{_MOOVENT_ACCENT}]"
              />
              <div class="mt-2 p-2.5 bg-gray-50 border border-gray-100 rounded-lg">
                <p class="text-xs text-gray-600">
                  <strong class="text-gray-700">What is this?</strong>
                  The Access URL is Moovent's internal endpoint that verifies you're an authorized developer. 
                  Your team lead will provide this URL when onboarding you.
                </p>
              </div>
            </div>

            <!-- Access Token field -->
            <div>
              <label class="block mb-2 text-sm font-medium text-gray-800">
                Access Token <span class="text-xs text-gray-400 font-normal">(if required)</span>
              </label>
              <input
                name="access_token"
                type="password"
                autocomplete="current-password"
                placeholder="moo_dev_xxxxxxxxxxxx"
                class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50 focus:border-[{_MOOVENT_ACCENT}]"
              />
              <div class="mt-2 p-2.5 bg-gray-50 border border-gray-100 rounded-lg">
                <p class="text-xs text-gray-600">
                  <strong class="text-gray-700">What is this?</strong>
                  A personal token that authenticates you to the access service. 
                  Some team configurations require it, others don't. Check with your team lead if unsure.
                  <span class="block mt-1 text-gray-500">Stored locally with restricted permissions (only you can read it).</span>
                </p>
              </div>
            </div>

            <!-- Workspace Folder field -->
            <div>
              <label class="block mb-2 text-sm font-medium text-gray-800">
                Workspace Folder <span class="text-red-500">*</span>
              </label>
              <input
                name="workspace_root"
                required
                autocomplete="off"
                placeholder="/Users/you/Projects/moovent"
                class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{_MOOVENT_ACCENT}]/50 focus:border-[{_MOOVENT_ACCENT}]"
              />
              <div class="mt-2 p-2.5 bg-gray-50 border border-gray-100 rounded-lg">
                <p class="text-xs text-gray-600">
                  <strong class="text-gray-700">What is this?</strong>
                  The folder where you cloned the Moovent repos. It must contain:
                </p>
                <ul class="mt-1.5 text-xs text-gray-600 space-y-0.5">
                  <li class="flex items-center gap-1.5">
                    <svg class="w-3 h-3" style="color: {_MOOVENT_ACCENT};" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>
                    <code class="px-1 py-0.5 bg-white border border-gray-200 rounded text-gray-700">mqtt_dashboard_watch/</code>
                    <span class="text-gray-500">(backend)</span>
                  </li>
                  <li class="flex items-center gap-1.5">
                    <svg class="w-3 h-3" style="color: {_MOOVENT_ACCENT};" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>
                    <code class="px-1 py-0.5 bg-white border border-gray-200 rounded text-gray-700">dashboard/</code>
                    <span class="text-gray-500">(frontend)</span>
                  </li>
                  <li class="flex items-center gap-1.5">
                    <svg class="w-3 h-3" style="color: {_MOOVENT_ACCENT};" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
                    <code class="px-1 py-0.5 bg-white border border-gray-200 rounded text-gray-700">run_local_stack.py</code>
                    <span class="text-gray-500">(launcher script)</span>
                  </li>
                </ul>
              </div>
            </div>

            <div class="pt-2">
              <button
                type="submit"
                class="py-3 px-4 w-full inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-transparent text-white hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2"
                style="background-color: {_MOOVENT_ACCENT}; --tw-ring-color: {_MOOVENT_ACCENT};"
              >
                Save &amp; Start Moovent Stack
                <svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M12 5l7 7-7 7"/></svg>
              </button>
            </div>

            <div class="p-3 bg-gray-50 border border-gray-200 rounded-lg">
              <p class="text-xs text-gray-600 flex items-center gap-1.5">
                <svg class="w-3.5 h-3.5 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"/></svg>
                Settings saved locally to
                <code class="px-1.5 py-0.5 rounded bg-white border border-gray-200 text-gray-700">~/.moovent_stack_config.json</code>
              </p>
            </div>
          </form>
        </div>

        <!-- Footer -->
        <p class="mt-6 text-center text-xs text-gray-500">
          Need help? Contact your team lead or check the
          <a href="https://github.com/Moovent/mqtt_dashboard_watch/blob/main/help/INSTALLATION.md" target="_blank" class="hover:underline" style="color: {_MOOVENT_ACCENT};">installation guide</a>.
        </p>
      </div>
    </main>
  </body>
</html>
""".strip()


def _success_page_html() -> str:
    """Render the success page after saving config (light mode only)."""
    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Ready - Moovent Stack</title>
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
