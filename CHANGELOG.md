# Changelog

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
