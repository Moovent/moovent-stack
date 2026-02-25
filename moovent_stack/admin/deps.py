"""
Dependency management for the admin dashboard.

Purpose:
  Ensure Node.js and Python dependencies are installed before starting services.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


def read_dotenv(path: Path) -> dict[str, str]:
    """
    Minimal .env parser.
    - Ignores comments + blank lines
    - Supports KEY=VALUE (optionally quoted)
    - Does NOT expand variables
    """
    out: dict[str, str] = {}
    try:
        if not path.exists():
            return out
        for raw in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            key = k.strip()
            val = v.strip().strip('"').strip("'")
            if key:
                out[key] = val
    except Exception:
        return out
    return out


def run_cmd(cmd: list[str], *, cwd: Path, env: Optional[dict[str, str]] = None) -> None:
    """Run a command and fail loudly if it errors."""
    subprocess.check_call(cmd, cwd=str(cwd), env=env or os.environ)


def _file_sha256(path: Path) -> str:
    """Return SHA256 for a file, or empty string when unavailable."""
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    return hashlib.sha256(data).hexdigest()


def _read_marker(marker: Path) -> str:
    """Read a dependency fingerprint marker file."""
    try:
        return marker.read_text(encoding="utf-8", errors="ignore").strip()
    except Exception:
        return ""


def _write_marker(marker: Path, value: str) -> None:
    """Write a dependency fingerprint marker file."""
    try:
        marker.write_text(f"{value}\n", encoding="utf-8")
    except Exception:
        pass


def _node_dep_fingerprint(project_dir: Path) -> str:
    """
    Build a node dependency fingerprint.

    Priority:
    - package-lock.json (most accurate for npm installs)
    - package.json fallback
    """
    lock = project_dir / "package-lock.json"
    if lock.exists():
        return f"lock:{_file_sha256(lock)}"
    pkg = project_dir / "package.json"
    return f"pkg:{_file_sha256(pkg)}"


def _python_dep_fingerprint(mqtt_repo: Path) -> str:
    """Build a python dependency fingerprint from requirements.txt."""
    req = mqtt_repo / "requirements.txt"
    return f"req:{_file_sha256(req)}"


def _vite_is_healthy(node_modules: Path) -> bool:
    """
    Check if Vite installation is healthy (all chunk files exist).
    
    Why:
      Vite can become internally inconsistent when `node_modules/vite` 
      has `cli.js` importing chunk files that don't exist, causing:
      ERR_MODULE_NOT_FOUND ... vite/dist/node/chunks/dep-XXXX.js
    """
    import re
    cli = node_modules / "vite" / "dist" / "node" / "cli.js"
    chunks_dir = node_modules / "vite" / "dist" / "node" / "chunks"
    
    if not cli.exists() or not chunks_dir.exists():
        return False
    
    try:
        text = cli.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    
    # Example in cli.js: import './chunks/dep-BK3b2jBa.js'
    refs = re.findall(r"""['"]\./chunks/(dep-[^'"]+\.js)['"]""", text)
    if not refs:
        # Unexpected format; assume ok if files exist
        return True
    
    for ref in set(refs):
        if not (chunks_dir / ref).exists():
            return False
    return True


def ensure_node_deps(project_dir: Path) -> None:
    """
    Ensure `npm install` has been run for a Node project.
    
    Also detects and repairs corrupted Vite installations.
    """
    import shutil
    
    if not (project_dir / "package.json").exists():
        raise FileNotFoundError(f"Missing package.json in {project_dir}")
    
    node_modules = project_dir / "node_modules"
    marker = project_dir / ".deps_installed"
    expected_fp = _node_dep_fingerprint(project_dir)
    current_fp = _read_marker(marker)
    
    # Check if node_modules exists and Vite is healthy
    needs_install = not node_modules.exists()
    if not needs_install and expected_fp and current_fp != expected_fp:
        print(f"[runner] Node deps changed in {project_dir}, reinstalling...", flush=True)
        needs_install = True
    if not needs_install and (node_modules / "vite").exists():
        if not _vite_is_healthy(node_modules):
            print(f"[runner] Corrupted Vite detected in {project_dir}, reinstalling...", flush=True)
            shutil.rmtree(node_modules, ignore_errors=True)
            needs_install = True
    
    if needs_install:
        print(f"[runner] Installing npm deps in {project_dir} ...", flush=True)
        lock = project_dir / "package-lock.json"
        mode = "ci" if lock.exists() else "install"
        run_cmd(["npm", mode, "--no-audit", "--no-fund"], cwd=project_dir)
        _write_marker(marker, expected_fp)
    elif expected_fp and not current_fp:
        # Backfill marker for existing healthy installs so future drift is detected.
        _write_marker(marker, expected_fp)


def ensure_python_deps(mqtt_repo: Path, system_python: str) -> str:
    """
    Ensure the mqtt backend virtualenv + requirements exist.

    Returns:
      Path to the venv python to use.
    """
    req = mqtt_repo / "requirements.txt"
    if not req.exists():
        raise FileNotFoundError(f"Missing requirements.txt in {mqtt_repo}")

    venv_dir = mqtt_repo / ".venv"
    venv_python = venv_dir / "bin" / "python"
    marker = venv_dir / ".deps_installed"
    expected_fp = _python_dep_fingerprint(mqtt_repo)
    current_fp = _read_marker(marker)

    if not venv_python.exists():
        print("[runner] Creating python venv for mqtt_dashboard_watch ...", flush=True)
        run_cmd([system_python, "-m", "venv", str(venv_dir)], cwd=mqtt_repo)

    py = str(venv_python) if venv_python.exists() else system_python

    if not marker.exists() or (expected_fp and current_fp != expected_fp):
        print("[runner] Installing python deps for mqtt_dashboard_watch ...", flush=True)
        run_cmd([py, "-m", "pip", "install", "-r", "requirements.txt"], cwd=mqtt_repo)
        _write_marker(marker, expected_fp)

    return py
