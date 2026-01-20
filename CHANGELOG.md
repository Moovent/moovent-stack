# Changelog

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
