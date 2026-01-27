# Getting Started — Moovent Stack

`moovent-stack` is a **local stack launcher** that:

- Validates access using **Infisical Universal Auth** (Machine Identity)
- Helps you choose a **workspace install path**
- Connects to GitHub via OAuth and clones the Moovent repos you select
- Runs your local stack via the **Admin Dashboard**

## Quickstart (recommended)

1) **Install**

```bash
brew install moovent/tap/moovent-stack
```

2) **Run**

```bash
moovent-stack
```

If setup is missing, a local setup page opens automatically.

## Setup flow (what you'll see)

### Step 1 — Infisical access

- Enter your **Infisical Client ID** and **Client Secret**
- `moovent-stack` immediately verifies your credentials can access the required Moovent project

Notes:
- Default host is **EU**: `https://eu.infisical.com`
- You can override with `INFISICAL_HOST`

### Step 2 — Workspace + GitHub

- Choose **Workspace Install Path**
  - Default: `~/Documents/Moovent-stack`
- Click **Connect GitHub**
  - This authorizes access to Moovent repos and stores an access token locally

Admin note:
- GitHub OAuth Client ID/Secret are fetched from Infisical (if available). If not, the UI shows "Contact your admin".

### Step 3 — Repo + branch selection

- Toggle which repos to install:
  - `mqtt_dashboard_watch` (backend service)
  - `dashboard` (frontend)
- Pick a branch per repo
- Click **Install Selected**

After cloning, `moovent-stack` writes **only non-sensitive Infisical scope config** to `mqtt_dashboard_watch/.env`
and then starts the Admin Dashboard.

## Admin Dashboard

After setup completes, the **Admin Dashboard** opens at:

**`http://127.0.0.1:9000`**

### Dashboard features

| Feature | Description |
|---------|-------------|
| **Service cards** | View all services with live status (listening/not listening) |
| **Start/Stop/Restart** | Control each service individually with one click |
| **Real-time logs** | SSE-streamed logs per service with auto-scroll |
| **Git info** | Current branch, commit, clean/dirty status |
| **Update detection** | Shows "Update available" when remote has new commits |
| **One-click update** | Fast-forward pull + automatic service restart |
| **GitHub OAuth** | Re-connect GitHub if token expires |

### Service ports

| Service | Port | URL |
|---------|------|-----|
| **Admin Dashboard** | 9000 | `http://127.0.0.1:9000` |
| MQTT UI | 3000 | `http://localhost:3000` |
| Dashboard UI | 4000 | `http://localhost:4000` |
| Backend API | 8000 | `http://localhost:8000` |

> **macOS note**: Use `127.0.0.1` instead of `localhost` for the admin dashboard to avoid AirPlay/AirTunes conflicts.

## Workspace requirements

Your workspace folder **must contain**:

- `run_local_stack.py` at the workspace root (auto-generated, delegates to admin module)
- `mqtt_dashboard_watch/` (repo folder, only if selected in Step 3)
- `dashboard/` (repo folder, only if selected in Step 3)

If these are missing, `moovent-stack` fails fast with a clear error.

## Keeping your stack up to date

The Admin Dashboard includes built-in update detection:

1. **Automatic check**: Dashboard periodically checks if `origin/<branch>` has new commits
2. **Update banner**: Shows "Update available" with commit count
3. **One-click update**: Click "Update now" to fast-forward pull and restart services

### Update behavior

- **Clean repos**: Can fast-forward (`git pull --ff-only`)
- **Dirty repos**: Never auto-updated (commit/stash first)
- **Auto-pull on launch**: Optionally pulls updates when dashboard starts (see `CONFIGURATION.md`)

## Stopping the stack

From the Admin Dashboard:
- Click **Stop** on individual services, or
- Close the terminal running `moovent-stack`

From terminal:

```bash
pkill -f moovent_stack.admin
```

## Secrets model (dev vs prod)

### Local development (dev)

- `moovent-stack` **does not write** `INFISICAL_CLIENT_ID` or `INFISICAL_CLIENT_SECRET` to disk in `.env`
- Instead, it injects them into the process environment when launching the admin module

### Production (Render)

- Set `INFISICAL_CLIENT_ID` and `INFISICAL_CLIENT_SECRET` as **Render environment variables**
