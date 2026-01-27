# Changelog

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
