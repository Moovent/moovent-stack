#!/usr/bin/env python3
"""
moovent-stack: internal dev launcher (local-only).

Entry point only. All logic lives in dedicated modules.
"""

from __future__ import annotations

from .app import main


if __name__ == "__main__":
    raise SystemExit(main())
