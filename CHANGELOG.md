# Changelog

## 0.5.5 (unreleased)
- **Fix (Infisical)**: Read `INFISICAL_EXPORT_ALL` from workspace `.env` so local runner injection can export all keys.

## 0.5.4
- **Infisical**: Add `INFISICAL_EXPORT_ALL=true` to export all keys from Infisical into the runtime env (recursive).
  - Applies to local runner injection and per-repo env switching (dev/prod).

## 0.5.3
- **Fix**: Environment badge icons now render correctly after service restart (Lucide icon timing fix).

## 0.5.2
- **New**: Per-repo Infisical environment switching (dev/prod).
  - Each service card now shows an environment badge (DEV = blue, PROD = red).
  - Click the badge to open a modal and switch between Development and Production databases.
  - Switching automatically re-fetches secrets from the selected Infisical environment and restarts affected services.
  - Access is controlled by your Infisical Machine Identity permissions.
  - Environment preference is saved per-repo in `~/.moovent_stack_config.json`.

## 0.5.1
- **New**: "Push to GitHub" button appears next to branch name when there are unpushed commits (ahead of origin).
  - Clicking the button pushes the current branch to GitHub without needing to open a terminal.
  - Shows success/error toast with details.
- **Fix**: Load `MOOVENT_INFISICAL_EXPORT_KEYS` from workspace `.env` before fetching Infisical secrets.
  - Previously, additional keys like `ANTHROPIC_API_KEY` weren't being exported because the config wasn't loaded.
  - Now the workspace's `.env` is read first, so user-specified export keys are properly fetched from Infisical.
- **UX**: Redesigned update banner card (cleaner layout, icon no longer cut off).
- **UX**: "View uncommitted changes" button when updates blocked by dirty repos — scrolls to the affected service card.
- **UX**: Remove hover zoom/translate effect on service cards.
- Note: "Unsaved work" badge still shows for uncommitted changes (can't be pushed directly — commit first).

## 0.5.0
- **Major**: Refactored admin dashboard into modular `moovent_stack.admin` package.
- New: Full-featured **Stack Admin Dashboard** (`http://127.0.0.1:9000`) with:
  - **Service control**: Start/stop/restart individual services with one click
  - **Real-time logs**: SSE-streamed logs per service with auto-scroll and filtering
  - **Git integration**: View current branch, detect updates, switch branches
  - **Git integration**: When a repo is behind, show a warning with a link to the latest upstream commit and a **danger-zone** “Update to latest” button (fast-forward only) + automatic service restart
  - **GitHub OAuth**: Re-connect GitHub from the dashboard if needed
  - **Update system**: One-click fast-forward pulls with automatic service restart
  - **Health checks**: Live status indicators for each service (listening/not listening)
- UX: “Development Stack” badge now sits closer to the Moovent logo in the header (left-aligned).
- Fix: prevent GitHub repository dropdown from closing during auto-refresh by skipping service-card DOM rebuilds while a repo `<select>` is focused.
- UX: rename MQTT services in the UI (“MQTT Backend”, “MQTT Dashboard”).
- UX: clicking Start/Restart/Stop now automatically switches the logs panel to that service.
- Fix: log switching is more robust when changing tabs quickly (prevents stale responses overwriting current logs).
- UX: added green "Turn on" button with confirmation modal (appears when all services are stopped, replaces red "Shutdown" button).
- Debug: enabled verbose console logging by default to diagnose dropdown auto-close issue.
- Removed: "Connect to GitHub repository" section from Options (not needed).
- Fix: branch dropdown works with backend git schema (ok/is_git, branch/branch_raw, branches/branches_local/branches_remote).
- UX: service issue toasts now auto-dismiss when the issue is resolved; MQTT Backend issues are toast-only (no inline red alert card).
- UX: log viewer now colorizes plain-text `INFO/WARN/ERROR/DEBUG` lines (improves MQTT Dashboard log readability).
- Fix: service restart now waits for process/port release before starting again (reduces “Port already in use” flapping).
- New: Admin module structure for maintainability:
  - `admin/__init__.py` — Entry point (`main()`) and orchestration
  - `admin/__main__.py` — Allows `python -m moovent_stack.admin`
  - `admin/config.py` — Configuration constants (ports, env helpers)
  - `admin/logs.py` — Per-service log ring buffers with SSE streaming
  - `admin/services.py` — Process manager (`StackManager`, start/stop/restart/health)
  - `admin/git_ops.py` — Git operations (branch switching, update detection, `GitCache`)
  - `admin/github.py` — GitHub OAuth helpers and API integration (`GitHubState`)
  - `admin/access.py` — Infisical access validation
  - `admin/updates.py` — Auto-update checks and one-click pulls (`UpdateState`)
  - `admin/deps.py` — Dependency management (npm, pip, venv)
  - `admin/server.py` — HTTP server, API endpoints, SSE implementation
  - `admin/templates/dashboard.html` — Full dashboard HTML/CSS/JS (~1700 lines)
- Change: `app.py` now launches the admin module directly (replaces old control UI + runner).
- Change: Setup now launches `python -m moovent_stack.admin` after install completes.
- Change: Generated `run_local_stack.py` is now a thin launcher that delegates to the admin module.
- Change: Default admin port changed from 7000 to **9000** to avoid macOS AirPlay/AirTunes conflict.
- Removed: Old `moovent_stack.control` module (replaced by admin dashboard).
- **Ports (stable)**:
  - `9000` — Stack Admin Dashboard
  - `3000` — MQTT Admin UI (`mqtt-admin-dashboard`)
  - `4000` — Dashboard UI (`dashboard` client)
  - `8000` — Backend API (`mqtt_dashboard_watch`)
- Fix: Services now start automatically when the admin dashboard launches.
- Fix: Graceful shutdown on Ctrl+C (SIGINT/SIGTERM) stops all child processes.

## 0.4.34
- Fix: use `http://127.0.0.1:7000` for Moovent Stack UI links to avoid macOS AirPlay/AirTunes 403 on `localhost:7000`.
- Fix: do not block mqtt backend startup when `MQTT_USER` is empty (local dev).

## 0.4.33
- UX: add Moovent Stack control UI on `http://127.0.0.1:7000` (stable place to manage and find links).
- Change: dashboard client uses `4000` even for dashboard-only installs (no more port 3000 reuse).
- UX: setup success page now links to Moovent Stack (7000) and shows MQTT (3000) + Dashboard (4000) separately.

## 0.4.32
- UX: "Open Dashboard" button now waits for dashboard to be ready before enabling.
- Fix: default dashboard URL changed from 5173 to 3000 in setup state.

## 0.4.31
- UX: show `pkill -f run_local_stack.py` command to stop all services after stack starts.

## 0.4.30
- Change: standardize port scheme to avoid collisions:
  - Setup UI: `7000` (was `9010`)
  - mqtt-admin-dashboard: `3000` (unchanged)
  - dashboard client: `4000` (was `5173` when both repos installed)
  - Backend API: `8000` (unchanged)

## 0.4.29
- UI: add Moovent favicon to setup pages (96x96 PNG, ICO, and Apple touch icon).

## 0.4.28
- Fix: stop running npm ci on every start (prevents node_modules disappearing under Vite).
- Fix: derive DB_NAME from MONGO_URI when exporting runtime env from Infisical.

## 0.4.27
- Fix: stop stray Vite processes from previous runs and enforce strict ports (keeps dashboard URL stable).
- Fix: add safe local defaults for missing MQTT/Mongo env so backend doesn't crash on missing secrets.

## 0.4.26
- Fix: auto-map legacy mqtt env secret names (MQTT_BROKER/MONGO_DB/etc.) to required runtime vars (BROKER/DB_NAME/etc.).
- Fix: clear Vite cache and start dev servers with --force to prevent 504 Outdated Optimize Dep white screens.

## 0.4.25
- Fix: export Infisical secrets recursively when exporting runtime env (supports foldered secrets).
- Fix: auto-create missing `mqtt-admin-dashboard/src/lib/utils.js` to prevent Vite alias import failures.

## 0.4.24
- Fix: export required mqtt_dashboard_watch env (BROKER/MONGO/etc.) from Infisical at runtime so backend doesn't crash.
- Fix: runner no longer stops the UI when the mqtt backend exits.

## 0.4.23
- Fix: auto-repair corrupted Vite installs by detecting missing chunk files and doing a clean npm reinstall.

## 0.4.22
- UX: removed helper text below Step 2 Continue button.
- Fix: always run npm install to fix corrupted node_modules.

## 0.4.21
- UX: grey out Step 2 Continue button until GitHub is connected.
- Fix: stack runner now logs to ~/.moovent_stack_runner.log for debugging.
- Fix: increased startup wait to 5s for npm install to complete.

## 0.4.20
- Fix: start the stack automatically after setup completes (no more "page not found" when clicking Open Dashboard).

## 0.4.19
- Fix: set a browser-like User-Agent for Infisical API calls (prevents Cloudflare 1010 blocks).

## 0.4.18
- Add: file-based logging to `~/.moovent_stack.log` for support diagnostics.
- Add: log path shown in error messages so users can share logs with support.
- Add: detailed Infisical auth failure logging.

## 0.4.17
- Fix: generated runner now installs dependencies and prints startup steps for clearer logs.

## 0.4.16
- UX: always open the dashboard on `http://localhost:3000` for consistent setup links.
- Fix: update generated runner to use port 3000 for dashboard-only installs.

## 0.4.15
- Fix: allow dashboard-only installs (skip mqtt validation when unselected).

## 0.4.14
- Fix: allow missing `dashboard/` when it wasn’t selected in setup.

## 0.4.13
- Fix: ensure `run_local_stack.py` is created in new workspaces so the stack can start after setup.
- UX: show an amber warning card on the installing page.

## 0.4.12
- Fix: default workspace path is persisted when Step 3 is reached via OAuth redirect.

## 0.4.11
- Docs: document local stack update behavior (auto-pull + one-click update).

## 0.4.10
- UX: add install progress page (backend-synced) while repositories are downloading/configuring.
- UX: success page now uses "Open the Dashboard" instead of closing the tab.

## 0.4.7
- Fix: derive org name from workspace API response (org endpoints can be blocked by Cloudflare).

## 0.4.8
- UX: move Infisical access scope display to Step 2; keep Step 1 focused on credentials entry.
- UX: hardcode org display name to "Moovent".

## 0.4.9
- UX: remove extra setup copy on Step 1.
- Fix: use default workspace path when Step 2 form submits empty value.

## 0.4.6
- UX: show resolved org/project names immediately after Step 1 auth.

## 0.4.5
- Debug: add verbose Infisical name lookup logging when `MOOVENT_INFISICAL_DEBUG=1`.

## 0.4.4
- Fix: expand fallback Infisical endpoints for org/workspace name lookups.

## 0.4.3
- Fix: add fallback Infisical endpoints for org/workspace name lookups.

## 0.4.2
- Fix: fetch org name from `/api/v1/organization/{orgId}` endpoint (workspace API doesn't return org name).

## 0.4.1
- UX: display human-readable org and project names in setup Step 1 (fetched from Infisical API) instead of UUIDs.

## 0.4.0
- Refactor: split monolithic `__main__.py` into focused modules (`config`, `storage`, `infisical`, `github`, `workspace`, `runner`, `access`, `app`) and a `setup/` subpackage for improved maintainability.
- Tests: update unit tests to target refactored modules directly.
- Docs: update `help/DEVELOPMENT.md` with new module layout.

## 0.3.12
- Change: pass Infisical "secret zero" to the dev stack at runtime (no longer written to `.env`).
- Change: keep `mqtt_dashboard_watch/.env` non-sensitive by only writing scope config.
- Docs: add `help/` documentation set (getting started, configuration, troubleshooting, security, development).
- UX: setup UI "Need help?" link now points to `moovent-stack` docs.

## 0.3.11
- UX: redesigned Step 3 with card-based repo selection (toggle on/off instead of text inputs).
- UX: repos are now optional - user can choose which to install via toggles.
- UX: branch selector only shows when repo is enabled; uses proper dropdown instead of datalist.
- UX: only shows repos the user has access to (hides repos with 403 errors).
- UX: better visual feedback with repo icons and descriptions.

## 0.3.10
- Fix: show actionable GitHub access errors (SSO/scopes) instead of generic reconnect.
- Fix: add GitHub User-Agent header to avoid 403s on branch fetch.

## 0.3.9
- Debug: show detailed error message when GitHub OAuth exchange fails.

## 0.3.8
- Fix: handle GitHub API 403 errors gracefully; show "token expired" message and allow reconnect.

## 0.3.7
- UX: add footer with Moovent copyright and version number to setup pages.

## 0.3.6
- UX: pre-fill workspace path with `~/Documents/Moovent-stack/` (works on Mac/Windows/Linux).

## 0.3.5
- Fix: fetch GitHub OAuth from Infisical on Step 2 load (handles users who completed Step 1 before 0.3.4).

## 0.3.4
- Simplify onboarding: GitHub OAuth credentials are now fetched automatically from Infisical after Step 1 succeeds.
- Remove "Admin settings" section from Step 2 (users no longer need to enter GitHub OAuth Client ID/Secret).
- Store secrets `MOOVENT_GITHUB_CLIENT_ID` and `MOOVENT_GITHUB_CLIENT_SECRET` in Infisical to enable this flow.

## 0.3.3
- Fix: use optimized (resized to 400px) Moovent logo PNG for onboarding header to reduce embedded base64 size from ~286KB to ~40KB.
- Change: default Infisical host to EU (`https://eu.infisical.com`); override with `INFISICAL_HOST` if needed.

## 0.3.2
- Fix: avoid denying access due to stale pre-project-scope access cache files.

## 0.3.1
- Step 1 now validates Infisical Universal Auth **and** access to the required project.
- Inject Infisical scope keys (`INFISICAL_HOST`, `INFISICAL_PROJECT_ID`, `INFISICAL_ENVIRONMENT`, `INFISICAL_SECRET_PATH`) into `mqtt_dashboard_watch/.env`.

## 0.3.0
- Added multi-step setup flow (Infisical, GitHub OAuth, branch selection).
- Added GitHub OAuth connect + repo/branch download.
- Inject Infisical creds into `mqtt_dashboard_watch/.env`.
