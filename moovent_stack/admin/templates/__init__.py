"""
HTML templates for the admin dashboard.

Purpose:
  Provide the dashboard HTML template as a string for the HTTP server.
"""

from __future__ import annotations

from pathlib import Path


def _load_template(name: str) -> str:
    """Load a template file from the templates directory."""
    template_dir = Path(__file__).parent
    template_path = template_dir / name
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    return ""


def get_dashboard_html() -> str:
    """Get the main dashboard HTML template."""
    return _load_template("dashboard.html")
