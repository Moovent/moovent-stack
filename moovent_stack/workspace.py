"""
Workspace validation and repo management.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .config import RUNNER_ENV_PATH, WORKSPACE_ENV_ROOT
from .infisical import _resolve_infisical_scope, _resolve_infisical_settings
from .storage import _load_config


def _resolve_runner_path() -> Optional[Path]:
    """Resolve the path to run_local_stack.py."""
    raw_runner = os.environ.get(RUNNER_ENV_PATH, "").strip()
    if raw_runner:
        return Path(raw_runner).expanduser()

    raw_root = os.environ.get(WORKSPACE_ENV_ROOT, "").strip()
    if raw_root:
        return Path(raw_root).expanduser() / "run_local_stack.py"

    cfg = _load_config()
    root = str(cfg.get("workspace_root") or "").strip()
    if root:
        return Path(root).expanduser() / "run_local_stack.py"

    return None


def _config_bool(value: object, default: bool) -> bool:
    """
    Convert config values into booleans with a safe default.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return default


def _validate_runner_path(
    path: Path, *, config_override: Optional[dict] = None
) -> tuple[bool, str]:
    """
    Validate workspace layout for local stack.

    Behavior:
      - If setup selections exist, require only the selected repos.
      - If no selections exist, infer required repos from what is present.
      - At least one repo must be available.
    """
    if not path.exists():
        return False, f"run_local_stack.py not found at: {path}"
    root = path.parent
    cfg = config_override if config_override is not None else _load_config()
    mqtt_exists = (root / "mqtt_dashboard_watch").exists()
    dash_exists = (root / "dashboard").exists()

    has_install_mqtt = "install_mqtt" in cfg
    has_install_dashboard = "install_dashboard" in cfg
    if has_install_mqtt or has_install_dashboard:
        require_mqtt = _config_bool(cfg.get("install_mqtt"), True)
        require_dashboard = _config_bool(cfg.get("install_dashboard"), True)
        if not require_mqtt and not require_dashboard:
            return False, "No repositories selected for installation."
    else:
        if mqtt_exists or dash_exists:
            require_mqtt = mqtt_exists
            require_dashboard = dash_exists
        else:
            require_mqtt = True
            require_dashboard = False

    missing = []
    if require_mqtt and not mqtt_exists:
        missing.append("mqtt_dashboard_watch/")
    if require_dashboard and not dash_exists:
        missing.append("dashboard/")
    if missing:
        return False, f"Workspace missing: {', '.join(missing)} (expected under {root})"
    return True, ""


def _default_workspace_path() -> str:
    """Return sensible default workspace path based on OS."""
    home = Path.home()
    docs = home / "Documents" / "Moovent-stack"
    return str(docs)


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


def _inject_infisical_env(workspace_root: Path) -> None:
    """
    Inject Infisical scope config into mqtt_dashboard_watch/.env.

    Purpose:
    - Keep `.env` non-sensitive (no secret zero stored on disk).
    - Pass Infisical client credentials at runtime via moovent-stack instead.
    """
    env_path = workspace_root / "mqtt_dashboard_watch" / ".env"
    if not env_path.parent.exists():
        # mqtt repo not installed; nothing to inject yet.
        return
    # Keep config aligned with mqtt_dashboard_watch Infisical loader env vars.
    # This prevents local runs failing due to missing project/environment settings.
    host, _, _ = _resolve_infisical_settings()
    project_id, environment, secret_path = _resolve_infisical_scope()
    _write_env_key(env_path, "INFISICAL_HOST", host)
    _write_env_key(env_path, "INFISICAL_PROJECT_ID", project_id)
    _write_env_key(env_path, "INFISICAL_ENVIRONMENT", environment)
    _write_env_key(env_path, "INFISICAL_SECRET_PATH", secret_path)


def _ensure_mqtt_admin_dashboard_shadcn_utils(workspace_root: Path) -> None:
    """
    Ensure mqtt-admin-dashboard has `src/lib/utils.js` (shadcn-style `cn()` helper).

    Why:
      Some UI components import `cn` from `@/lib/utils`, but the file can be missing
      in certain branches. This causes Vite to fail to start with:
        Failed to resolve import "@/lib/utils"

    Behavior:
      - Create the file if missing (do not overwrite).
      - Keep it minimal and dependency-aligned with existing package.json.
    """
    utils_path = (
        workspace_root
        / "mqtt_dashboard_watch"
        / "mqtt-admin-dashboard"
        / "src"
        / "lib"
        / "utils.js"
    )
    if utils_path.exists():
        return
    utils_path.parent.mkdir(parents=True, exist_ok=True)
    utils_path.write_text(
        "\n".join(
            [
                'import clsx from "clsx";',
                'import { twMerge } from "tailwind-merge";',
                "",
                "/**",
                " * Merge Tailwind class names safely.",
                " *",
                " * Purpose:",
                " *  - Used by shadcn/ui-style components (e.g. `@/components/ui/*`).",
                " */",
                "export function cn(...inputs) {",
                "  return twMerge(clsx(inputs));",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _ensure_workspace_runner(workspace_root: Path) -> None:
    """
    Ensure `<workspace>/run_local_stack.py` exists.

    Why:
      The launcher expects a workspace-level runner script. Some setups only clone
      repos and forget to include the runner, which prevents the stack from starting.

    Behavior:
      - If the file exists: do nothing (never overwrite).
      - If missing: write a small runner that starts available services.
    """
    runner_path = workspace_root / "run_local_stack.py"
    marker = "run_local_stack.py (generated by moovent-stack)"
    if runner_path.exists():
        try:
            existing = runner_path.read_text(encoding="utf-8")
        except Exception:
            return
        if marker not in existing:
            return

    content = """#!/usr/bin/env python3
\"\"\"
run_local_stack.py (generated by moovent-stack)

Purpose:
  Start the local Moovent stack from a workspace folder created by moovent-stack.

Notes:
  - This file is generated only if missing; it is safe to customize afterwards.
  - Services are started best-effort; this script keeps running until you Ctrl+C.
\"\"\"

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time
import shutil
from pathlib import Path


def _popen(cmd: list[str], cwd: Path, env: dict[str, str]) -> subprocess.Popen:
    # Purpose: launch child and inherit stdout/stderr for visibility.
    return subprocess.Popen(cmd, cwd=str(cwd), env=env)  # noqa: S603,S607


def _clear_vite_cache(project_dir: Path) -> None:
    \"\"\"
    Remove Vite prebundle caches.

    Why:
      Vite can serve 504 "Outdated Optimize Dep" when the prebundled deps are stale.
      Clearing the cache + starting with `--force` makes startup reliable.
    \"\"\"
    for p in [
        project_dir / "node_modules" / ".vite",
        project_dir / ".vite",
    ]:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)


def _kill_stray_vite(root: Path, ports: list[int]) -> None:
    \"\"\"
    Kill stray Vite dev servers from previous runs.

    Why:
      Setup can start the stack in the background; repeated installs can leave
      old Vite processes running on 3000/4000, causing port drift and
      white screens / stale optimize deps.

    Safety:
      - Only kills processes that are listening on the target ports AND whose
        command line contains this workspace path and `node_modules/.bin/vite`.
    \"\"\"
    if shutil.which("lsof") is None or shutil.which("ps") is None:
        return

    def _pids_for_port(port: int) -> list[int]:
        try:
            out = subprocess.check_output(
                ["lsof", "-nP", "-iTCP:%d" % port, "-sTCP:LISTEN", "-t"],
                text=True,
            ).strip()
        except Exception:
            return []
        pids: list[int] = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pids.append(int(line))
            except ValueError:
                continue
        return pids

    def _cmd(pid: int) -> str:
        try:
            return subprocess.check_output(
                ["ps", "-p", str(pid), "-o", "command="], text=True
            ).strip()
        except Exception:
            return ""

    def _kill(pid: int) -> None:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            return

    root_s = str(root)
    for port in ports:
        for pid in _pids_for_port(port):
            cmd = _cmd(pid)
            if not cmd:
                continue
            if root_s in cmd and "node_modules/.bin/vite" in cmd:
                print(f"[runner] Stopping stray Vite (pid={pid}) on port {port}…", flush=True)
                _kill(pid)


def _apply_mqtt_env_aliases() -> None:
    \"\"\"
    Map legacy env names to required mqtt_dashboard_watch names.

    Why:
      Some setups store these keys as `MQTT_BROKER`, `MQTT_USERNAME`, `MQTT_PASSWORD`,
      and `MONGO_DB`, while the backend requires `BROKER`, `MQTT_USER`, `MQTT_PASS`,
      `DB_NAME`, and `COL_*` at import time.
    \"\"\"
    if not os.environ.get("BROKER"):
        os.environ["BROKER"] = os.environ.get("MQTT_BROKER", "").strip()
    if not os.environ.get("MQTT_USER"):
        os.environ["MQTT_USER"] = os.environ.get("MQTT_USERNAME", "").strip()
    if not os.environ.get("MQTT_PASS"):
        os.environ["MQTT_PASS"] = os.environ.get("MQTT_PASSWORD", "").strip()
    if not os.environ.get("MONGO_URI"):
        os.environ["MONGO_URI"] = os.environ.get("MONGODB_URI", "").strip()
    if not os.environ.get("MONGO_URI"):
        os.environ["MONGO_URI"] = "mongodb://localhost:27017/"
    if not os.environ.get("DB_NAME"):
        # Try common aliases first.
        os.environ["DB_NAME"] = os.environ.get("MONGO_DB", "").strip()
        # Best-effort derive DB name from URI path: mongodb://.../<db>?...
        if not os.environ["DB_NAME"]:
            uri = os.environ.get("MONGO_URI", "").strip()
            if uri and "/" in uri:
                tail = uri.rsplit("/", 1)[-1].split("?", 1)[0].strip()
                if tail and "@" not in tail and ":" not in tail:
                    os.environ["DB_NAME"] = tail
        if not os.environ["DB_NAME"]:
            os.environ["DB_NAME"] = "mqtt_dashboard"
    # Safe defaults for local dev when secrets are missing.
    if not os.environ.get("BROKER"):
        os.environ["BROKER"] = "localhost"
    if os.environ.get("MQTT_USER") is None:
        os.environ["MQTT_USER"] = ""
    if os.environ.get("MQTT_PASS") is None:
        os.environ["MQTT_PASS"] = ""
    os.environ.setdefault("COL_DEVICES", "devices")
    os.environ.setdefault("COL_PARKINGS", "parkings")
    os.environ.setdefault("COL_TOTALS", "totals")
    os.environ.setdefault("COL_BUCKETS", "buckets")


def _ensure_node_deps(path: Path) -> None:
    \"\"\"
    Ensure Node dependencies are installed (and not corrupted).

    Why:
      We have seen cases where `node_modules/vite` becomes internally inconsistent:
      `vite/dist/node/cli.js` imports a chunk file that doesn't exist, causing:
      ERR_MODULE_NOT_FOUND ... vite/dist/node/chunks/dep-XXXX.js

    Logic:
      - Never run `npm ci` on every start (it deletes node_modules).
      - If `node_modules` is missing or looks corrupted, do a clean reinstall.
      - Otherwise, keep existing deps (fast + avoids breaking a running dev server).
    \"\"\"
    lock = path / "package-lock.json"
    node_modules = path / "node_modules"

    def _vite_is_healthy() -> bool:
        cli = node_modules / "vite" / "dist" / "node" / "cli.js"
        chunks_dir = node_modules / "vite" / "dist" / "node" / "chunks"
        if not cli.exists() or not chunks_dir.exists():
            return False
        try:
            text = cli.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return False
        # Example in cli.js: import './chunks/dep-BK3b2jBa.js'
        refs = re.findall(r\"\"\"['"]\\./chunks/(dep-[^'"]+\\.js)['\"]\"\"\", text)
        if not refs:
            # Unexpected format; assume ok if files exist.
            return True
        for ref in set(refs):
            if not (chunks_dir / ref).exists():
                return False
        return True

    needs_clean = (not node_modules.exists()) or (node_modules.exists() and not _vite_is_healthy())
    if not needs_clean:
        return

    print("[runner] Ensuring no Vite is running before reinstall…", flush=True)
    # Best-effort kill any vite processes that point at this project (prevents ENOENT during npm ci).
    if shutil.which("ps") is not None:
        try:
            out = subprocess.check_output(["ps", "ax", "-o", "pid=,command="], text=True)
        except Exception:
            out = ""
        needle = str(path / "node_modules" / ".bin" / "vite")
        for line in out.splitlines():
            if needle in line:
                try:
                    pid = int(line.strip().split(None, 1)[0])
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass
        time.sleep(0.5)

    if node_modules.exists():
        print("[runner] Cleaning node_modules…", flush=True)
        shutil.rmtree(node_modules, ignore_errors=True)

    mode = "ci" if lock.exists() else "install"
    print(f"[runner] Installing node deps in {path} (npm {mode})...", flush=True)
    cmd = ["npm", mode, "--no-audit", "--no-fund"]
    subprocess.check_call(cmd, cwd=str(path))


def _ensure_python_venv(repo: Path) -> str:
    # Purpose: isolate python deps for mqtt backend.
    venv_dir = repo / ".venv"
    python = venv_dir / "bin" / "python"
    if not python.exists():
        print(f"[runner] Creating venv in {venv_dir}...", flush=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])
    req = repo / "requirements.txt"
    if req.exists():
        print("[runner] Installing python deps...", flush=True)
        subprocess.check_call([str(python), "-m", "pip", "install", "-r", str(req)])
    return str(python)


def main() -> int:
    root = Path(__file__).resolve().parent
    mqtt_repo = root / "mqtt_dashboard_watch"
    dash_repo = root / "dashboard"

    mqtt_exists = mqtt_repo.exists()
    dash_exists = dash_repo.exists()

    if not mqtt_exists and not dash_exists:
        print(
            f"[runner] No repositories installed under {root}. "
            "Expected mqtt_dashboard_watch/ or dashboard/.",
            file=sys.stderr,
        )
        return 2

    if shutil.which("npm") is None:
        print("[runner] npm not found in PATH", file=sys.stderr)
        return 2

    # Track running child processes.
    # Each entry: (name, process, critical)
    procs: list[tuple[str, subprocess.Popen, bool]] = []

    def _stop_all() -> None:
        for _name, p, _critical in procs:
            try:
                p.send_signal(signal.SIGTERM)
            except Exception:
                continue
        time.sleep(0.8)
        for _name, p, _critical in procs:
            try:
                p.kill()
            except Exception:
                continue

    def _handle_sig(_sig: int, _frame: object) -> None:
        print("\\n[runner] Stopping…", flush=True)
        _stop_all()
        raise SystemExit(0)

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    urls = []

    if mqtt_exists:
        _apply_mqtt_env_aliases()
        _kill_stray_vite(root, [3000, 4000])
        py_cmd = _ensure_python_venv(mqtt_repo)
        admin_dir = mqtt_repo / "mqtt-admin-dashboard"
        _ensure_node_deps(admin_dir)
        _clear_vite_cache(admin_dir)
        # mqtt_dashboard_watch backend requires these env vars at import-time.
        required = [
            "BROKER",
            "MQTT_USER",
            "MQTT_PASS",
            "MONGO_URI",
            "DB_NAME",
            "COL_DEVICES",
            "COL_PARKINGS",
            "COL_TOTALS",
            "COL_BUCKETS",
        ]
        missing = [k for k in required if not str(os.environ.get(k, "")).strip()]
        # mqtt backend
        backend_env = dict(os.environ)
        backend_env.setdefault("PORT", "8000")
        backend_env["ALLOW_START_WITHOUT_MQTT"] = "true"
        if missing:
            print(
                "[runner] mqtt backend not started (missing env): "
                + ", ".join(missing),
                file=sys.stderr,
            )
        else:
            procs.append(
                (
                    "mqtt-backend",
                    _popen([py_cmd, "src/main.py"], cwd=mqtt_repo, env=backend_env),
                    False,
                )
            )

        # mqtt admin dashboard (vite)
        procs.append(
            (
                "mqtt-admin-dashboard",
                _popen(
                    ["npm", "run", "dev", "--", "--port", "3000", "--strictPort", "--force"],
                    cwd=admin_dir,
                    env=dict(os.environ),
                ),
                True,
            )
        )
        urls.append("http://localhost:3000")

    # Optional dashboard repo (if present)
    if dash_exists:
        _ensure_node_deps(dash_repo / "server")
        client_dir = dash_repo / "client"
        _ensure_node_deps(client_dir)
        _clear_vite_cache(client_dir)
        server_env = dict(os.environ)
        server_env["PORT"] = server_env.get("PORT", "5001")
        procs.append(
            (
                "dashboard-server",
                _popen(
                    ["npm", "run", "dev"],
                    cwd=dash_repo / "server",
                    env=server_env,
                ),
                False,
            )
        )
        dash_port = "3000" if not mqtt_exists else "4000"
        _kill_stray_vite(root, [3000, 4000])
        procs.append(
            (
                "dashboard-client",
                _popen(
                    ["npm", "run", "dev", "--", "--force", "--port", dash_port, "--strictPort"],
                    cwd=client_dir,
                    env=dict(os.environ),
                ),
                True,
            )
        )
        urls.insert(0, f"http://localhost:{dash_port}")

    print("[runner] Stack starting…", flush=True)
    for u in urls:
        print(f"[runner] Open: {u}", flush=True)

    # Keep alive until interrupted.
    while True:
        for name, p, critical in list(procs):
            if p.poll() is not None:
                code = p.returncode
                print(f"[runner] Service exited: {name} (code={code})", file=sys.stderr)
                if critical:
                    print("[runner] A critical service exited. Stopping stack.", file=sys.stderr)
                    _stop_all()
                    return 1
                # Non-critical: keep stack running.
                procs.remove((name, p, critical))
        time.sleep(0.5)


if __name__ == "__main__":
    raise SystemExit(main())
"""

    runner_path.write_text(content, encoding="utf-8")
    try:
        runner_path.chmod(0o755)
    except Exception:
        pass


def _run_git(cmd: list[str], cwd: Path) -> None:
    """Run git command with safe defaults."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    subprocess.check_call(cmd, cwd=str(cwd), env=env)


def _clone_or_update_repo(
    owner: str, repo: str, branch: str, dest: Path, token: str
) -> None:
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
