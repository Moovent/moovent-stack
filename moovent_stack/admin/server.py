"""
HTTP server and request handler for the admin dashboard.

Purpose:
  Serve the admin UI and handle API endpoints for service control,
  logs, git operations, and GitHub OAuth.
"""

from __future__ import annotations

import json
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, unquote, urlparse

from .config import (
    ADMIN_BIND,
    DEFAULT_ADMIN_PORT,
    DEFAULT_LOG_TAIL,
    GITHUB_SCOPES,
    GITHUB_REPOS_CACHE_TTL_S,
    GITHUB_BRANCHES_CACHE_TTL_S,
)
from .templates import get_dashboard_html
from .github import (
    github_config,
    save_github_config,
    github_authorize_url,
    github_exchange_code,
    github_fetch_user,
    github_fetch_repos,
    github_fetch_branches,
    valid_github_full_name,
    git_connect_repo,
    GitHubState,
)
from .git_ops import GitCache, git_checkout_branch, git_pull_latest
from .updates import UpdateState

if TYPE_CHECKING:
    from .logs import LogStore
    from .services import StackManager


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    """
    Quiet server: ignore noisy disconnect errors.

    Why:
      Browsers can reset connections (reloads, navigation, tab close) which
      triggers ConnectionResetError in BaseHTTPRequestHandler, and the
      default server prints a full traceback. That's expected noise in local dev.
    """

    def handle_error(self, request: object, client_address: object) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        return super().handle_error(request, client_address)


def build_admin_server(
    manager: "StackManager",
    log_store: "LogStore",
    git_cache: GitCache,
    github_state: GitHubState,
    update_state: UpdateState,
    github_client_id: str,
    github_client_secret: str,
    host: str = ADMIN_BIND,
    port: int = DEFAULT_ADMIN_PORT,
) -> ThreadingHTTPServer:
    """
    Build the admin HTTP server (UI + API).

    Assumption:
      Local only. We bind to 127.0.0.1 and do not enable auth.
    """
    # IMPORTANT: GitHub OAuth requires exact callback URL matching.
    redirect_uri = f"http://{host}:{port}/oauth/callback"
    dashboard_html = get_dashboard_html()

    class AdminHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            # Silence default HTTP logs to keep terminal clean.
            return

        def _send_json(self, payload: dict[str, object], status: int = 200) -> None:
            data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_text(self, body: str, status: int = 200, content_type: str = "text/html") -> None:
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _read_json_body(self) -> dict[str, object]:
            """Parse JSON request body. Returns {} on empty/invalid payloads."""
            try:
                length = int(self.headers.get("Content-Length", "0") or 0)
            except Exception:
                length = 0
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8", errors="ignore")
            try:
                return json.loads(raw)
            except Exception:
                return {}

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            qs = parse_qs(parsed.query)

            # Main dashboard
            if path == "/":
                self._send_text(dashboard_html)
                return

            # Health check
            if path == "/health":
                self._send_json({"ok": True})
                return

            # Services status
            if path == "/api/services":
                self._send_json({
                    "services": manager.status_snapshot(),
                    "timestamp": time.time(),
                })
                return

            # Update status
            if path == "/api/update/status":
                force = (qs.get("force") or ["0"])[0] in ("1", "true", "yes", "on")
                self._send_json(update_state.status(force_check=force))
                return

            # GitHub status
            if path == "/api/github/status":
                current_id, current_secret = github_config()
                user = github_state.user or {}
                has_token = github_state.access_token is not None
                self._send_json({
                    "connected": has_token,
                    "authenticated": has_token,  # Legacy field
                    "login": user.get("login", ""),
                    "user": user,
                    "can_auth": bool(current_id and current_secret),
                })
                return

            # GitHub login redirect
            if path == "/api/github/login":
                current_id, current_secret = github_config()
                if not current_id or not current_secret:
                    self._send_json({"error": "oauth_not_configured"}, status=400)
                    return
                state_token = secrets.token_urlsafe(16)
                github_state.oauth_state = state_token
                auth_url = github_authorize_url(
                    current_id,
                    redirect_uri,
                    state_token,
                    GITHUB_SCOPES,
                )
                print(f"[github-oauth] Login redirect. redirect_uri={redirect_uri}", flush=True)
                self.send_response(302)
                self.send_header("Location", auth_url)
                self.end_headers()
                return

            # GitHub OAuth callback
            if path == "/oauth/callback":
                code = (qs.get("code") or [""])[0]
                returned_state = (qs.get("state") or [""])[0]
                expected_state = github_state.oauth_state
                
                if not code:
                    self._send_text("Missing code. Close this tab and retry.", status=400)
                    return
                if expected_state and returned_state != expected_state:
                    self._send_text("State mismatch. Close this tab and retry.", status=400)
                    return
                
                current_id, current_secret = github_config()
                if not current_id or not current_secret:
                    self._send_text("OAuth not configured.", status=400)
                    return
                
                ok, token, _ = github_exchange_code(current_id, current_secret, code, redirect_uri)
                if not ok:
                    self._send_text(f"OAuth exchange failed: {token}", status=400)
                    return
                
                ok, user, _ = github_fetch_user(token)
                if not ok:
                    self._send_text("Failed to fetch user.", status=400)
                    return
                
                github_state.access_token = token
                github_state.user = user
                
                self.send_response(302)
                self.send_header("Location", "/")
                self.end_headers()
                return

            # GitHub repos
            if path == "/api/github/repos":
                token = github_state.access_token
                if not token:
                    self._send_json({"error": "not_authenticated"}, status=401)
                    return
                repos = github_state.get_repos(token)
                self._send_json({"repos": repos})
                return

            # GitHub branches
            if path == "/api/github/branches":
                token = github_state.access_token
                if not token:
                    self._send_json({"error": "not_authenticated"}, status=401)
                    return
                repo_full_name = (qs.get("repo") or [""])[0]
                if not valid_github_full_name(repo_full_name):
                    self._send_json({"error": "invalid_repo"}, status=400)
                    return
                branches = github_state.get_branches(token, repo_full_name)
                self._send_json({"branches": branches})
                return

            # Git info for a service
            if path.startswith("/api/git/"):
                name = unquote(path.split("/api/git/", 1)[1])
                if not name or "/" in name:
                    self._send_json({"error": "bad_request"}, status=400)
                    return
                spec = manager.services.get(name)
                if not spec or not spec.repo:
                    self._send_json({"error": "unknown_service"}, status=404)
                    return
                force = (qs.get("force") or ["0"])[0] in ("1", "true", "yes", "on")
                info = git_cache.get_info(spec.repo, force=force)
                info["service"] = name
                self._send_json(info)
                return

            # Logs for a service
            if path.startswith("/api/logs/") and path != "/api/logs/stream":
                name = unquote(path.split("/api/logs/", 1)[1])
                if not name or name not in manager.services:
                    self._send_json({"error": "unknown_service"}, status=404)
                    return
                tail_str = (qs.get("tail") or [str(DEFAULT_LOG_TAIL)])[0]
                try:
                    tail = int(tail_str)
                except Exception:
                    tail = DEFAULT_LOG_TAIL
                entries = log_store.tail(name, tail)
                min_id = log_store.min_id(name)
                max_id = log_store.max_id(name)
                self._send_json({
                    "service": name,
                    "entries": [entry.to_dict() for entry in entries],
                    "min_id": min_id,
                    "max_id": max_id,
                    "truncated": (
                        min_id is not None and max_id is not None and
                        (max_id - min_id + 1) > len(entries)
                    ),
                })
                return

            # Log streaming (SSE)
            if path == "/api/logs/stream":
                name = (qs.get("name") or [""])[0]
                if not name or name not in manager.services:
                    self._send_json({"error": "unknown_service"}, status=404)
                    return
                since_str = (qs.get("since") or ["0"])[0]
                try:
                    last_id = int(since_str)
                except Exception:
                    last_id = 0
                self._serve_sse(name, last_id)
                return

            self._send_json({"error": "not_found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"

            # Trigger update
            if path == "/api/update/run":
                result = update_state.run_update(reason="manual")
                self._send_json(result)
                return

            # Service actions
            if path.startswith("/api/services/"):
                _, _, tail = path.partition("/api/services/")
                parts = tail.split("/")
                if len(parts) != 2:
                    self._send_json({"error": "bad_request"}, status=400)
                    return
                name = unquote(parts[0])
                action = parts[1]
                if name not in manager.services:
                    self._send_json({"error": "unknown_service"}, status=404)
                    return
                if action == "start":
                    ok = manager.start(name)
                elif action == "stop":
                    ok = manager.stop(name)
                elif action == "restart":
                    ok = manager.restart(name)
                else:
                    self._send_json({"error": "unknown_action"}, status=400)
                    return
                self._send_json({"ok": ok, "service": name, "action": action})
                return

            # GitHub logout
            if path == "/api/github/logout":
                github_state.clear()
                self._send_json({"ok": True})
                return

            # Save GitHub credentials
            if path == "/api/github/setup/save":
                payload = self._read_json_body()
                client_id = str(payload.get("client_id") or "").strip()
                client_secret = str(payload.get("client_secret") or "").strip()
                if not client_id or len(client_id) < 10:
                    self._send_json({"ok": False, "error": "Invalid Client ID"}, status=400)
                    return
                if not client_secret or len(client_secret) < 10:
                    self._send_json({"ok": False, "error": "Invalid Client Secret"}, status=400)
                    return
                saved = save_github_config(client_id, client_secret)
                if saved:
                    self._send_json({"ok": True, "message": "Credentials saved."})
                else:
                    self._send_json({"ok": False, "error": "Failed to save"}, status=500)
                return

            # Git operations
            if path.startswith("/api/git/"):
                _, _, tail = path.partition("/api/git/")
                parts = tail.split("/")
                if len(parts) != 2:
                    self._send_json({"error": "bad_request"}, status=400)
                    return
                name = unquote(parts[0])
                action = parts[1]
                
                spec = manager.services.get(name)
                if not spec or not spec.repo:
                    self._send_json({"error": "unknown_service"}, status=404)
                    return
                
                if action == "connect":
                    token = github_state.access_token
                    if not token:
                        self._send_json({"error": "not_authenticated"}, status=401)
                        return
                    payload = self._read_json_body()
                    repo_full_name = str(payload.get("repo") or "").strip()
                    branch = str(payload.get("branch") or "").strip()
                    ok, message = git_connect_repo(spec.repo, repo_full_name, branch)
                    if not ok:
                        self._send_json({"ok": False, "error": message})
                        return
                    git_cache.invalidate(spec.repo)
                    restarted: list[str] = []
                    for svc_name in manager.services_for_repo(spec.repo):
                        manager.log_store.append(svc_name, f"[runner] git connect {repo_full_name}@{branch}")
                        if manager.desired_running.get(svc_name, False):
                            manager.restart(svc_name)
                            restarted.append(svc_name)
                    self._send_json({
                        "ok": True,
                        "service": name,
                        "repo": repo_full_name,
                        "branch": branch,
                        "restarted": restarted,
                    })
                    return
                
                if action == "checkout":
                    payload = self._read_json_body()
                    branch = str(payload.get("branch") or "").strip()
                    ok, message = git_checkout_branch(spec.repo, branch)
                    if not ok:
                        self._send_json({"ok": False, "error": message})
                        return
                    git_cache.invalidate(spec.repo)
                    restarted: list[str] = []
                    for svc_name in manager.services_for_repo(spec.repo):
                        manager.log_store.append(svc_name, f"[runner] git checkout {branch}")
                        if manager.desired_running.get(svc_name, False):
                            manager.restart(svc_name)
                            restarted.append(svc_name)
                    self._send_json({
                        "ok": True,
                        "service": name,
                        "branch": branch,
                        "restarted": restarted,
                        "message": message,
                    })
                    return

                if action == "pull":
                    ok, code, detail = git_pull_latest(spec.repo)
                    if not ok:
                        self._send_json({"ok": False, "error": code, "detail": detail})
                        return

                    git_cache.invalidate(spec.repo)
                    restarted: list[str] = []
                    for svc_name in manager.services_for_repo(spec.repo):
                        manager.log_store.append(svc_name, "[runner] git pull --ff-only")
                        if manager.desired_running.get(svc_name, False):
                            manager.restart(svc_name)
                            restarted.append(svc_name)

                    self._send_json({
                        "ok": True,
                        "service": name,
                        "status": code,  # "updated" | "up_to_date"
                        "detail": detail,
                        "restarted": restarted,
                    })
                    return
                
                self._send_json({"error": "unknown_action"}, status=400)
                return

            # Stack-wide actions
            if path.startswith("/api/stack/"):
                _, _, action = path.partition("/api/stack/")
                if action == "start":
                    manager.start_all()
                elif action == "stop":
                    manager.stop_all()
                elif action == "restart":
                    manager.restart_all()
                else:
                    self._send_json({"error": "unknown_action"}, status=400)
                    return
                self._send_json({"ok": True, "action": action})
                return

            self._send_json({"error": "not_found"}, status=404)

        def _serve_sse(self, name: str, last_id: int) -> None:
            """Serve Server-Sent Events for real-time log streaming."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            try:
                while True:
                    entries = log_store.since(name, last_id, limit=200)
                    if entries:
                        for entry in entries:
                            data = json.dumps(entry.to_dict(), ensure_ascii=True)
                            self.wfile.write(f"id: {entry.id}\n".encode("utf-8"))
                            self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                            last_id = entry.id
                        self.wfile.flush()
                        continue

                    # No new data; send a keep-alive comment.
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
                    if not log_store.wait_for_new(name, last_id, timeout_s=1.5):
                        continue
            except (BrokenPipeError, ConnectionResetError):
                return
            except Exception:
                return

    server = QuietThreadingHTTPServer((host, port), AdminHandler)
    server.daemon_threads = True
    return server
