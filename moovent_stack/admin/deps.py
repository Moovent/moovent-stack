"""
Dependency management for the admin dashboard.

Purpose:
  Ensure Node.js and Python dependencies are installed before starting services.
"""

from __future__ import annotations

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
    
    # Check if node_modules exists and Vite is healthy
    needs_install = not node_modules.exists()
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

    if not venv_python.exists():
        print("[runner] Creating python venv for mqtt_dashboard_watch ...", flush=True)
        run_cmd([system_python, "-m", "venv", str(venv_dir)], cwd=mqtt_repo)

    py = str(venv_python) if venv_python.exists() else system_python

    if not marker.exists():
        print("[runner] Installing python deps for mqtt_dashboard_watch ...", flush=True)
        run_cmd([py, "-m", "pip", "install", "-r", "requirements.txt"], cwd=mqtt_repo)
        try:
            marker.write_text("ok\n", encoding="utf-8")
        except Exception:
            pass

    return py
