"""
Allow running the admin module directly: python -m moovent_stack.admin
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import main


if __name__ == "__main__":
    # Allow passing workspace path as argument
    workspace_path = None
    if len(sys.argv) > 1:
        workspace_path = Path(sys.argv[1]).resolve()
    raise SystemExit(main(workspace_path))
