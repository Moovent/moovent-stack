"""
File-based logging for moovent-stack.

Purpose:
  Capture detailed logs to a file so users can share with support when errors occur.

Usage:
  from .log import log_info, log_error, log_debug, get_log_path
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path
from threading import Lock
from typing import Optional

# Log file path (user-configurable via env)
LOG_ENV_PATH = "MOOVENT_LOG_PATH"
LOG_ENV_LEVEL = "MOOVENT_LOG_LEVEL"  # debug, info, error
DEFAULT_LOG_PATH = Path.home() / ".moovent_stack.log"
MAX_LOG_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB rotation threshold

_lock = Lock()
_log_path: Optional[Path] = None


def _resolve_log_path() -> Path:
    """Resolve log file path from env or default."""
    raw = os.environ.get(LOG_ENV_PATH, "").strip()
    return Path(raw) if raw else DEFAULT_LOG_PATH


def _log_level() -> str:
    """Return configured log level (debug, info, error). Default: info."""
    raw = os.environ.get(LOG_ENV_LEVEL, "").strip().lower()
    if raw in {"debug", "info", "error"}:
        return raw
    return "info"


def get_log_path() -> Path:
    """Return the path to the log file."""
    global _log_path
    if _log_path is None:
        _log_path = _resolve_log_path()
    return _log_path


def _rotate_if_needed(path: Path) -> None:
    """
    Rotate log file if it exceeds MAX_LOG_SIZE_BYTES.

    Keeps one backup (.log.1) to avoid unbounded disk usage.
    """
    try:
        if not path.exists():
            return
        if path.stat().st_size < MAX_LOG_SIZE_BYTES:
            return
        backup = path.with_suffix(".log.1")
        if backup.exists():
            backup.unlink()
        path.rename(backup)
    except Exception:
        pass


def _write_log(level: str, tag: str, message: str) -> None:
    """
    Append a log line to the log file.

    Format: TIMESTAMP LEVEL [tag] message
    """
    path = get_log_path()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{ts} {level.upper():5} [{tag}] {message}\n"

    with _lock:
        _rotate_if_needed(path)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
        except Exception:
            # If we can't write to the log file, print to stderr as fallback.
            print(f"[log-error] {line.strip()}", file=sys.stderr)


def log_debug(tag: str, message: str) -> None:
    """Log a debug-level message (only if MOOVENT_LOG_LEVEL=debug)."""
    if _log_level() == "debug":
        _write_log("debug", tag, message)


def log_info(tag: str, message: str) -> None:
    """Log an info-level message."""
    level = _log_level()
    if level in {"debug", "info"}:
        _write_log("info", tag, message)


def log_error(tag: str, message: str) -> None:
    """Log an error-level message (always logged)."""
    _write_log("error", tag, message)


def log_startup() -> None:
    """Log moovent-stack startup with version info."""
    from .config import __version__

    log_info("startup", f"moovent-stack v{__version__} starting")
    log_info("startup", f"Log file: {get_log_path()}")
    log_info("startup", f"Log level: {_log_level()}")
