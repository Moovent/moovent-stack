"""
Moovent Stack local control UI (localhost-only).

Purpose:
  Provide a stable, Moovent-stack-owned page on http://127.0.0.1:7000
  to avoid confusion with app/service UIs (MQTT, dashboard, backend).

Design goals:
  - Stdlib only (Homebrew-friendly, no extra deps)
  - Localhost-only binding (127.0.0.1)
  - Read-only by default (shows status + commands; does not execute destructive ops)
  - Robust even if the actual stack processes are not running
"""

from __future__ import annotations

import json
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import __version__, _setup_port
from .storage import _load_config


def _port_open(port: int, *, host: str = "127.0.0.1", timeout_s: float = 0.25) -> bool:
    """Return True if TCP connection succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _status_snapshot() -> dict[str, object]:
    """
    Build a lightweight status snapshot.

    Notes:
      We intentionally avoid shelling out or reading process tables.
      Port probes are the safest cross-platform signal that a service is listening.
    """
    cfg = _load_config()
    workspace_root = str(cfg.get("workspace_root") or "").strip()
    root = Path(workspace_root).expanduser() if workspace_root else None

    mqtt_installed = bool(root and (root / "mqtt_dashboard_watch").exists())
    dashboard_installed = bool(root and (root / "dashboard").exists())

    return {
        "ts": int(time.time()),
        "version": __version__,
        "workspace_root": workspace_root,
        "installed": {"mqtt": mqtt_installed, "dashboard": dashboard_installed},
        "ports": {
            # Moovent-stack UI (this server)
            "moovent_stack_ui": {"port": _setup_port(), "listening": True},
            # App/service UIs
            "mqtt_ui": {"port": 3000, "listening": _port_open(3000)},
            "dashboard_ui": {"port": 4000, "listening": _port_open(4000)},
            "mqtt_backend": {"port": 8000, "listening": _port_open(8000)},
        },
        "commands": {
            # Single-shot kill command users can copy/paste.
            "stop_all": "pkill -f run_local_stack.py",
        },
    }


def _index_html() -> str:
    """Render a small control page (no external assets)."""
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Moovent Stack</title>
    <style>
      body {{ font-family: -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif; background:#0b1220; color:#e5e7eb; margin:0; }}
      .wrap {{ max-width: 820px; margin: 0 auto; padding: 28px 18px; }}
      .card {{ background:#0f1b33; border:1px solid #1f2a44; border-radius:14px; padding:18px; }}
      a.button {{ display:inline-block; padding:10px 12px; border-radius:10px; text-decoration:none; color:#0b1220; background:#f7c948; font-weight:600; }}
      a.ghost {{ background:transparent; color:#e5e7eb; border:1px solid #334155; }}
      .row {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }}
      code {{ background:#0b1220; border:1px solid #22304a; padding:2px 6px; border-radius:8px; }}
      .muted {{ color:#9ca3af; }}
      .k {{ color:#cbd5e1; }}
      .ok {{ color:#34d399; }}
      .bad {{ color:#fb7185; }}
      ul {{ margin: 10px 0 0 18px; }}
    </style>
  </head>
  <body>
    <div class="wrap">
      <div class="card">
        <div class="muted">Moovent Stack control UI (localhost-only)</div>
        <h1 style="margin:10px 0 6px 0;">Moovent Stack <span class="muted" style="font-size:14px;">v{__version__}</span></h1>
        <div class="muted">This page is served by moovent-stack on <code>http://127.0.0.1:{_setup_port()}</code>.</div>

        <div class="row">
          <a class="button ghost" href="http://127.0.0.1:3000" target="_blank" rel="noopener noreferrer">Open MQTT UI (3000)</a>
          <a class="button ghost" href="http://127.0.0.1:4000" target="_blank" rel="noopener noreferrer">Open Dashboard UI (4000)</a>
          <a class="button ghost" href="http://127.0.0.1:8000" target="_blank" rel="noopener noreferrer">Open Backend (8000)</a>
        </div>

        <h3 style="margin:16px 0 8px 0;">Status</h3>
        <div id="status" class="muted">Loading…</div>

        <h3 style="margin:16px 0 8px 0;">Stop everything</h3>
        <div class="muted">Copy/paste in a terminal:</div>
        <div style="margin-top:6px;"><code>pkill -f run_local_stack.py</code></div>
      </div>
    </div>

    <script>
      function badge(ok) {{
        return ok ? '<span class="ok">listening</span>' : '<span class="bad">not listening</span>';
      }}
      async function poll() {{
        try {{
          const res = await fetch("/api/status", {{ cache: "no-store" }});
          const data = await res.json();
          const p = data.ports || {{}};
          const installed = (data.installed || {{}});
          const root = data.workspace_root || "";
          const html = `
            <div><span class="k">Workspace:</span> <code>${{root || "(not set)"}}</code></div>
            <ul>
              <li><span class="k">MQTT UI (3000):</span> ${{badge(!!(p.mqtt_ui && p.mqtt_ui.listening))}}</li>
              <li><span class="k">Dashboard UI (4000):</span> ${{badge(!!(p.dashboard_ui && p.dashboard_ui.listening))}}</li>
              <li><span class="k">Backend (8000):</span> ${{badge(!!(p.mqtt_backend && p.mqtt_backend.listening))}}</li>
            </ul>
            <div class="muted" style="margin-top:8px;">
              Installed repos: mqtt=${{installed.mqtt ? "yes" : "no"}}, dashboard=${{installed.dashboard ? "yes" : "no"}}
            </div>
          `;
          const el = document.getElementById("status");
          if (el) el.innerHTML = html;
        }} catch (e) {{
          // ignore transient errors
        }}
        setTimeout(poll, 1000);
      }}
      poll();
    </script>
  </body>
</html>
""".strip()


def main() -> int:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args) -> None:
            return

        def _send_json(self, code: int, payload: dict[str, object]) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _send_html(self, code: int, html: str) -> None:
            raw = html.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send_json(200, {"ok": True, "ts": int(time.time())})
                return
            if self.path == "/api/status":
                self._send_json(200, _status_snapshot())
                return
            if self.path == "/" or self.path.startswith("/?"):
                self._send_html(200, _index_html())
                return
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"Not found")

    server = ThreadingHTTPServer(("127.0.0.1", _setup_port()), Handler)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
