# Changelog

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
