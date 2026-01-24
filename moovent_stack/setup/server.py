"""
Local HTTP setup server.
"""

from __future__ import annotations

import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs

from ..config import (
    DEFAULT_GITHUB_SCOPES,
    DEFAULT_INFISICAL_ENVIRONMENT,
    DEFAULT_INFISICAL_SECRET_PATH,
    REQUIRED_INFISICAL_ORG_ID,
    REQUIRED_INFISICAL_PROJECT_ID,
    _setup_port,
)
from ..github import (
    _github_exchange_code,
    _github_get_login,
    _github_list_branches,
    _resolve_github_oauth_settings,
    _resolve_github_token,
)
from ..infisical import (
    _ensure_github_oauth_from_infisical,
    _fetch_infisical_access,
    _fetch_github_oauth_from_infisical,
    _fetch_scope_display_names,
    _resolve_infisical_settings,
)
from ..storage import _load_config, _save_config
from ..workspace import _clone_or_update_repo, _inject_infisical_env
from .templates import (
    _setup_step1_confirm_html,
    _setup_step1_html,
    _setup_step2_html,
    _setup_step3_html,
    _success_page_html,
)


def _open_browser(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception:
        print("[runner] Unable to open browser automatically.", file=sys.stderr)


def _run_setup_server() -> None:
    """
    Launch a local setup page to collect credentials + install settings.
    """

    class _SetupState:
        done: bool = False
        oauth_state: Optional[str] = None
        base_url: Optional[str] = None

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

        def _next_step(self) -> int:
            cfg = _load_config()
            if (
                not str(cfg.get("infisical_client_id") or "").strip()
                or not str(cfg.get("infisical_client_secret") or "").strip()
            ):
                return 1
            if not str(cfg.get("workspace_root") or "").strip():
                return 2
            if not str(cfg.get("github_access_token") or "").strip():
                return 2
            return 3

        def do_GET(self) -> None:
            cfg = _load_config()
            if self.path == "/" or self.path.startswith("/?"):
                step = self._next_step()
                if step == 1:
                    # Use cached display names if available
                    org_name = str(cfg.get("infisical_org_name") or "").strip() or None
                    project_name = (
                        str(cfg.get("infisical_project_name") or "").strip() or None
                    )
                    self._send(
                        200,
                        _setup_step1_html(org_name=org_name, project_name=project_name),
                    )
                    return
                if step == 2:
                    # Try to fetch GitHub OAuth from Infisical if missing
                    _ensure_github_oauth_from_infisical()
                    cfg = _load_config()  # reload after potential update
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    oauth_ready = all(_resolve_github_oauth_settings())
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                            oauth_ready=oauth_ready,
                        ),
                    )
                    return
                token = _resolve_github_token() or ""
                if not token:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="Connect GitHub before selecting branches.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        ),
                    )
                    return

                mqtt_branches, mqtt_error, mqtt_reconnect = _github_list_branches(
                    "Moovent", "mqtt_dashboard_watch", token
                )
                dash_branches, dash_error, dash_reconnect = _github_list_branches(
                    "Moovent", "dashboard", token
                )
                errors = [err for err in (mqtt_error, dash_error) if err]
                if errors:
                    # Use <br/> to preserve multiple error lines in the HTML block.
                    error_text = "<br/>".join(errors)
                    if mqtt_reconnect or dash_reconnect:
                        _save_config({"github_access_token": "", "github_login": ""})
                        github_login = None
                    else:
                        github_login = (
                            str(cfg.get("github_login") or "").strip() or None
                        )
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text=error_text,
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        ),
                    )
                    return

                self._send(200, _setup_step3_html(mqtt_branches, dash_branches))
                return

            if self.path.startswith("/oauth/start"):
                # Try to fetch GitHub OAuth from Infisical if missing
                _ensure_github_oauth_from_infisical()
                client_id, client_secret = _resolve_github_oauth_settings()
                if not client_id or not client_secret:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="GitHub OAuth Client ID/Secret is required.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                            oauth_ready=False,
                        ),
                    )
                    return
                state.oauth_state = secrets.token_urlsafe(16)
                redirect_uri = f"{state.base_url}/oauth/callback"
                auth_url = (
                    "https://github.com/login/oauth/authorize"
                    f"?client_id={client_id}"
                    f"&redirect_uri={redirect_uri}"
                    f"&scope={DEFAULT_GITHUB_SCOPES.replace(' ', '%20')}"
                    f"&state={state.oauth_state}"
                )
                self.send_response(302)
                self.send_header("Location", auth_url)
                self.end_headers()
                return

            if self.path.startswith("/oauth/callback"):
                params = parse_qs(self.path.split("?", 1)[-1])
                state_param = (params.get("state", [""])[0] or "").strip()
                code = (params.get("code", [""])[0] or "").strip()
                if not state.oauth_state or state_param != state.oauth_state:
                    self._send(400, "Invalid OAuth state", "text/plain")
                    return
                client_id, client_secret = _resolve_github_oauth_settings()
                if not client_id or not client_secret:
                    self._send(400, "GitHub OAuth not configured", "text/plain")
                    return
                try:
                    token = _github_exchange_code(client_id, client_secret, code)
                except Exception:
                    self._send(
                        200,
                        _setup_step2_html(
                            None,
                            error_text="GitHub OAuth failed. Please retry.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        ),
                    )
                    return
                login = _github_get_login(token)
                _save_config(
                    {
                        "github_access_token": token,
                        "github_login": login or "",
                    }
                )
                self.send_response(302)
                self.send_header("Location", "/step3")
                self.end_headers()
                return

            if self.path.startswith("/step1"):
                # Use cached display names if available
                org_name = str(cfg.get("infisical_org_name") or "").strip() or None
                project_name = (
                    str(cfg.get("infisical_project_name") or "").strip() or None
                )
                self._send(
                    200,
                    _setup_step1_html(org_name=org_name, project_name=project_name),
                )
                return

            if self.path.startswith("/step2"):
                # Try to fetch GitHub OAuth from Infisical if missing
                _ensure_github_oauth_from_infisical()
                cfg = _load_config()  # reload after potential update
                github_login = str(cfg.get("github_login") or "").strip() or None
                oauth_ready = all(_resolve_github_oauth_settings())
                self._send(
                    200,
                    _setup_step2_html(
                        github_login,
                        workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        oauth_ready=oauth_ready,
                    ),
                )
                return

            if self.path.startswith("/step3"):
                token = _resolve_github_token() or ""
                if not token:
                    github_login = str(cfg.get("github_login") or "").strip() or None
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="Connect GitHub before selecting branches.",
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        ),
                    )
                    return
                mqtt_branches, mqtt_error, mqtt_reconnect = _github_list_branches(
                    "Moovent", "mqtt_dashboard_watch", token
                )
                dash_branches, dash_error, dash_reconnect = _github_list_branches(
                    "Moovent", "dashboard", token
                )
                errors = [err for err in (mqtt_error, dash_error) if err]
                if errors:
                    # Use <br/> to preserve multiple error lines in the HTML block.
                    error_text = "<br/>".join(errors)
                    if mqtt_reconnect or dash_reconnect:
                        _save_config({"github_access_token": "", "github_login": ""})
                        github_login = None
                    else:
                        github_login = (
                            str(cfg.get("github_login") or "").strip() or None
                        )
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text=error_text,
                            workspace_root=str(cfg.get("workspace_root") or "").strip(),
                        ),
                    )
                    return
                self._send(200, _setup_step3_html(mqtt_branches, dash_branches))
                return

            self._send(404, "Not found", "text/plain")

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or "0")
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            form = parse_qs(raw)

            if self.path == "/save-step1":
                client_id = (form.get("client_id", [""])[0] or "").strip()
                client_secret = (form.get("client_secret", [""])[0] or "").strip()
                if not client_id:
                    self._send(
                        200, _setup_step1_html("Infisical Client ID is required.")
                    )
                    return
                if not client_secret:
                    self._send(
                        200, _setup_step1_html("Infisical Client Secret is required.")
                    )
                    return

                host, _, _ = _resolve_infisical_settings()
                allowed, reason = _fetch_infisical_access(
                    host, client_id, client_secret
                )
                if not allowed:
                    # Try to fetch display names for nicer error page
                    project_name, org_name = _fetch_scope_display_names(
                        host, client_id, client_secret
                    )
                    self._send(
                        200,
                        _setup_step1_html(
                            "Infisical access check failed. "
                            f"Reason: {reason}. "
                            "Ensure your Machine Identity has access to the required project.",
                            org_name=org_name,
                            project_name=project_name,
                        ),
                    )
                    return

                # Fetch display names and GitHub OAuth creds from Infisical
                project_name, org_name = _fetch_scope_display_names(
                    host, client_id, client_secret
                )
                github_id, github_secret = _fetch_github_oauth_from_infisical(
                    host, client_id, client_secret
                )

                config_data = {
                    "infisical_client_id": client_id,
                    "infisical_client_secret": client_secret,
                    "infisical_host": host,
                    # Persist enforced scope so other steps can reuse it.
                    "infisical_org_id": REQUIRED_INFISICAL_ORG_ID,
                    "infisical_project_id": REQUIRED_INFISICAL_PROJECT_ID,
                    # Store display names for UI
                    "infisical_org_name": org_name or "",
                    "infisical_project_name": project_name or "",
                    "infisical_environment": DEFAULT_INFISICAL_ENVIRONMENT,
                    "infisical_secret_path": DEFAULT_INFISICAL_SECRET_PATH,
                }
                # Auto-populate GitHub OAuth if found in Infisical
                if github_id:
                    config_data["github_client_id"] = github_id
                if github_secret:
                    config_data["github_client_secret"] = github_secret

                _save_config(config_data)

                # Show resolved names immediately on Step 1 confirmation
                org_display = org_name or REQUIRED_INFISICAL_ORG_ID
                project_display = project_name or REQUIRED_INFISICAL_PROJECT_ID
                self._send(
                    200,
                    _setup_step1_confirm_html(
                        org_name=org_display, project_name=project_display
                    ),
                )
                return

            if self.path == "/save-step2":
                workspace_root = (form.get("workspace_root", [""])[0] or "").strip()
                if not workspace_root:
                    github_login = (
                        str(_load_config().get("github_login") or "").strip() or None
                    )
                    self._send(
                        200,
                        _setup_step2_html(
                            github_login,
                            error_text="Workspace path is required.",
                            workspace_root="",
                        ),
                    )
                    return

                _save_config({"workspace_root": str(Path(workspace_root).expanduser())})

                self.send_response(302)
                self.send_header("Location", "/step3")
                self.end_headers()
                return

            if self.path == "/save-step3":
                token = _resolve_github_token()
                if not token:
                    self._send(
                        200, _setup_step2_html(None, error_text="Connect GitHub first.")
                    )
                    return

                # Check which repos are selected for installation
                install_mqtt = "install_mqtt" in form
                install_dashboard = "install_dashboard" in form

                if not install_mqtt and not install_dashboard:
                    self._send(
                        200,
                        _setup_step3_html(
                            [], [], "Please select at least one repository to install."
                        ),
                    )
                    return

                mqtt_branch = (form.get("mqtt_branch", ["main"])[0] or "main").strip()
                dashboard_branch = (
                    form.get("dashboard_branch", ["main"])[0] or "main"
                ).strip()
                cfg = _load_config()
                workspace_root = str(cfg.get("workspace_root") or "").strip()
                if not workspace_root:
                    self._send(
                        200,
                        _setup_step2_html(
                            None, error_text="Workspace path is required."
                        ),
                    )
                    return

                try:
                    root = Path(workspace_root).expanduser()

                    # Only clone selected repos
                    if install_mqtt:
                        _clone_or_update_repo(
                            "Moovent",
                            "mqtt_dashboard_watch",
                            mqtt_branch,
                            root / "mqtt_dashboard_watch",
                            token,
                        )

                    if install_dashboard:
                        _clone_or_update_repo(
                            "Moovent",
                            "dashboard",
                            dashboard_branch,
                            root / "dashboard",
                            token,
                        )

                    _inject_infisical_env(root)

                    _save_config(
                        {
                            "mqtt_branch": mqtt_branch if install_mqtt else "",
                            "dashboard_branch": (
                                dashboard_branch if install_dashboard else ""
                            ),
                            "install_mqtt": install_mqtt,
                            "install_dashboard": install_dashboard,
                            "setup_complete": True,
                        }
                    )
                    state.done = True
                    self._send(200, _success_page_html())
                except Exception as exc:
                    self._send(
                        200, _setup_step3_html([], [], f"Download failed: {exc}")
                    )
                return

            self._send(404, "Not found", "text/plain")

    try:
        server = ThreadingHTTPServer(("127.0.0.1", _setup_port()), Handler)
    except OSError as exc:
        print(f"[setup] Unable to start local setup server: {exc}", file=sys.stderr)
        raise SystemExit(2)
    host, port = server.server_address
    setup_url = f"http://{host}:{port}/"
    state.base_url = f"http://{host}:{port}"

    print("[setup] Setup is not configured. Opening setup page…")
    print(f"[setup] {setup_url}")
    _open_browser(setup_url)

    while not state.done:
        server.handle_request()

    try:
        server.server_close()
    except Exception:
        pass
