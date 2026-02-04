# Configuration — Moovent Stack

This page documents how `moovent-stack` is configured:

- Environment variables (`INFISICAL_*`, `MOOVENT_*`)
- Local config/cache files under your home directory
- How the launcher passes Infisical credentials to the stack at runtime

## How configuration is resolved

`moovent-stack` resolves settings in this order:

- **Environment variables**
- **Local config file** `~/.moovent_stack_config.json`

Access decisions are cached in:

- `~/.moovent_stack_access.json` (path override: `MOOVENT_ACCESS_CACHE_PATH`)

## Infisical configuration

### Required (credentials)

These are needed for `moovent-stack` to authenticate your access.

```bash
export INFISICAL_CLIENT_ID="..."
export INFISICAL_CLIENT_SECRET="..."
```

### Scope (enforced)

`moovent-stack` enforces a **single Moovent project** for access control.

- The required project is baked into the launcher and verified during Step 1.
- If you explicitly set `INFISICAL_PROJECT_ID` to a different value, access validation fails with `project_id_mismatch`.

### Optional

```bash
# Default: https://eu.infisical.com (EU). US: https://app.infisical.com
export INFISICAL_HOST="https://eu.infisical.com"

# These control where secrets are read in Infisical for the child stack:
export INFISICAL_ENVIRONMENT="dev"   # default: dev
export INFISICAL_SECRET_PATH="/"     # default: /

# When true, export *all* secrets/config from Infisical into the runtime env
# of the child stack (recursive). This enables "Infisical is the source of truth"
# for both secrets and non-secret config flags.
export INFISICAL_EXPORT_ALL="true"
```

### Exported keys (defaults vs export-all)

- Default behavior: `moovent-stack` exports only the baseline keys required for the stack to boot
  (Mongo/MQTT/collections), plus any extra keys listed in `MOOVENT_INFISICAL_EXPORT_KEYS`.
- If `INFISICAL_EXPORT_ALL=true`: `moovent-stack` exports **all** keys in the configured
  Infisical environment/path (recursive). `MOOVENT_INFISICAL_EXPORT_KEYS` becomes optional.

## GitHub configuration

### GitHub OAuth App (admin-provisioned)

The setup UI uses a GitHub OAuth app to obtain a user token that can read Moovent repos/branches.

These values are normally fetched from Infisical and stored in `~/.moovent_stack_config.json`:

- `MOOVENT_GITHUB_CLIENT_ID`
- `MOOVENT_GITHUB_CLIENT_SECRET`

You can also provide them via env vars:

```bash
export MOOVENT_GITHUB_CLIENT_ID="..."
export MOOVENT_GITHUB_CLIENT_SECRET="..."
```

### GitHub access token (user OAuth)

After you click **Connect GitHub**, the access token is stored in `~/.moovent_stack_config.json`.

You can override it via:

```bash
export MOOVENT_GITHUB_ACCESS_TOKEN="..."
```

## Runner / workspace configuration

`moovent-stack` launches your local stack by running the **Admin Dashboard** module.

### Option A (recommended): set workspace root

```bash
export MOOVENT_WORKSPACE_ROOT="$HOME/Documents/Moovent-stack"
```

### Option B: set runner path directly

```bash
export MOOVENT_RUNNER_PATH="/full/path/to/run_local_stack.py"
```

## Admin Dashboard configuration

The Admin Dashboard runs on port **9000** by default.

```bash
# Change the admin dashboard port (default: 9000)
export MOOVENT_SETUP_PORT=9000
```

### Port scheme (stable)

| Service | Default Port | Notes |
|---------|--------------|-------|
| Admin Dashboard | 9000 | Use `127.0.0.1` on macOS |
| MQTT UI | 3000 | `mqtt-admin-dashboard` |
| Dashboard UI | 4000 | `dashboard` client |
| Backend API | 8000 | `mqtt_dashboard_watch` |

## Local stack auto-update

The Admin Dashboard can check for repo updates and auto-pull on launch.

### Behavior

- Auto-pull only happens on launch, and only when the repo is clean.
- Dirty worktrees are never auto-pulled.
- Updates use fast-forward only (`git pull --ff-only`).

### Environment variables

```bash
# Enable/disable update checks (default: true)
export MOOVENT_AUTOUPDATE_ENABLED=1

# Enable/disable auto-pull on launch (default: true)
export MOOVENT_AUTOUPDATE_AUTOPULL=1

# How often the dashboard refreshes update status (seconds, default: 3600)
export MOOVENT_AUTOUPDATE_CHECK_INTERVAL_S=3600
```

### Remote mode

When running the stack in "remote mode" (e.g., deployed to Render), auto-update is disabled:

```bash
export MOOVENT_REMOTE_MODE=1
```

## Setup server configuration

The interactive setup runs a local HTTP server on port `9000` by default.

```bash
export MOOVENT_SETUP_PORT=9000
```

If the port is already in use, change it and re-run.

To disable the setup UI and fail fast when config is missing:

```bash
export MOOVENT_SETUP_NONINTERACTIVE=1
```

## Access caching & self-clean

### Cache TTL

```bash
# Default: 86400 (24h)
export MOOVENT_ACCESS_TTL_S=86400
```

### Cache file path

```bash
export MOOVENT_ACCESS_CACHE_PATH="$HOME/.moovent_stack_access.json"
```

### Optional: self-clean on revoke

If access is denied and this is enabled, the launcher can remove its own Homebrew install
and delete local cache files.

```bash
export MOOVENT_ACCESS_SELF_CLEAN=1
```

Homebrew install root is provided by the environment when installed via Homebrew:

- `MOOVENT_INSTALL_ROOT`

## Runtime environment injection (important)

To keep secrets off disk in dev mode:

- `moovent-stack` injects these into the environment when starting the admin module:
  - `INFISICAL_ENABLED=true`
  - `INFISICAL_CLIENT_ID`
  - `INFISICAL_CLIENT_SECRET`
  - `INFISICAL_HOST` (if set)
  - `INFISICAL_PROJECT_ID`, `INFISICAL_ENVIRONMENT`, `INFISICAL_SECRET_PATH`

- Additionally, `moovent-stack` exports required stack secrets (like `BROKER`, `MONGO_URI`, etc.)
  from Infisical **at runtime** into the local stack environment (still not written to disk).
  You can override which keys are exported:

```bash
export MOOVENT_INFISICAL_EXPORT_KEYS="BROKER,MQTT_USER,MQTT_PASS,MONGO_URI,DB_NAME,COL_DEVICES,COL_PARKINGS,COL_TOTALS,COL_BUCKETS"
```

Additionally, it writes **only non-sensitive scope keys** into:

- `<workspace>/mqtt_dashboard_watch/.env`

It does **not** write `INFISICAL_CLIENT_ID` or `INFISICAL_CLIENT_SECRET` into `.env`.

## Log files

| Log file | Purpose |
|----------|---------|
| `~/.moovent_stack.log` | Main launcher logs |
| `~/.moovent_stack_admin.log` | Admin dashboard logs (when launched in background) |
