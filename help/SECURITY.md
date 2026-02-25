# Security — Moovent Stack

This document explains the security model and assumptions of `moovent-stack`.

## What `moovent-stack` protects

`moovent-stack` is an **internal launcher**. Its main goal is to ensure that only users with valid access:

- can clone Moovent repositories via GitHub OAuth
- can start the local development stack
- can read secrets (indirectly) via Infisical

## Access control (Infisical Universal Auth)

On every run, the launcher performs an Infisical Universal Auth check:

- Uses `INFISICAL_CLIENT_ID` + `INFISICAL_CLIENT_SECRET`
- Verifies the Machine Identity can access the **required Moovent project**
- Caches the allow/deny result for a limited time (TTL)

### Cache TTL and file

- TTL: `MOOVENT_ACCESS_TTL_S` (default 24 hours)
- Cache path: `MOOVENT_ACCESS_CACHE_PATH` (default `~/.moovent_stack_access.json`)

The cache file is written with restricted permissions where possible.

## Secret handling ("secret zero")

Infisical "secret zero" is the Universal Auth credentials:

- `INFISICAL_CLIENT_ID`
- `INFISICAL_CLIENT_SECRET`

**Important:** the launcher is designed so that local stack repos do not need to store these on disk.

### Local development

- `moovent-stack` uses `INFISICAL_CLIENT_ID` and `INFISICAL_CLIENT_SECRET` in the launcher process
  to fetch runtime keys.
- Child service environments receive only resolved runtime settings/secrets; `INFISICAL_CLIENT_SECRET`
  is not propagated to child processes.
- `moovent-stack` writes only non-sensitive Infisical scope keys to
  `<workspace>/mqtt_dashboard_watch/.env`.

### Production (Render)

- Set Infisical credentials as Render environment variables
- Do not commit them into any `.env` file

## GitHub OAuth

The launcher uses a GitHub OAuth app to request a user token for:

- listing branches
- cloning private repositories

The access token is stored in `~/.moovent_stack_config.json` with restricted permissions where possible.

## Network exposure

### Admin Dashboard (port 9000)

The Admin Dashboard binds to `127.0.0.1:9000` by default:

- **Only accessible from localhost**
- Cannot be accessed from other machines on the network
- No authentication required (localhost-only assumption)

### Child services

Child services (MQTT UI, Dashboard, Backend) bind to `localhost` or `0.0.0.0` depending on their configuration:

- Check individual service documentation for network exposure
- For production, use proper firewalls and reverse proxies

## Optional self-clean on revoke

If `MOOVENT_ACCESS_SELF_CLEAN=1` is set and access is denied, the launcher can attempt to:

- delete its Homebrew installation directory (provided via `MOOVENT_INSTALL_ROOT`)
- delete access cache files

This is intended as a defense-in-depth measure for internal distribution.

## Log files

Log files may contain:

- Service names and ports
- File paths
- Error messages

Log files do **not** contain:

- Infisical credentials
- GitHub tokens
- Database credentials

Log file locations:

| File | Contents |
|------|----------|
| `~/.moovent_stack.log` | Main launcher logs |
| `~/.moovent_stack_admin.log` | Admin dashboard logs |

## Assumptions / non-goals

- This is **not** a hardened security boundary against a malicious local admin.
- The launcher assumes the workstation is trusted and not compromised.
- The launcher does not implement disk encryption; rely on OS-level security controls.
- The Admin Dashboard assumes localhost access is trusted (no auth).
