# Getting Started — Moovent Stack

`moovent-stack` is a **local stack launcher** that:

- Validates access using **Infisical Universal Auth** (Machine Identity)
- Helps you choose a **workspace install path**
- Connects to GitHub via OAuth and clones the Moovent repos you select
- Runs your local stack via `run_local_stack.py`

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

## Setup flow (what you’ll see)

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
- GitHub OAuth Client ID/Secret are fetched from Infisical (if available). If not, the UI shows “Contact your admin”.

### Step 3 — Repo + branch selection

- Toggle which repos to install:
  - `mqtt_dashboard_watch` (backend service)
  - `dashboard` (frontend)
- Pick a branch per repo
- Click **Install Selected**

After cloning, `moovent-stack` writes **only non-sensitive Infisical scope config** to `mqtt_dashboard_watch/.env`
and then starts the stack.

## Workspace requirements

Your workspace folder **must contain**:

- `run_local_stack.py` at the workspace root
- `mqtt_dashboard_watch/` (repo folder, only if selected in Step 3)
- `dashboard/` (repo folder, only if selected in Step 3)

If these are missing, `moovent-stack` fails fast with a clear error.

## Keeping your stack up to date

Your workspace runner (`run_local_stack.py`) includes a local **Stack Admin UI** (runs on localhost) that can:

- Detect repo updates (behind `origin/<branch>`)
- Show an **Update available** banner
- Run a **one-click update** (fast-forward only) and restart services for updated repos

Notes:

- Updates are **safe by default**:
  - Clean repos: can fast-forward (`git pull --ff-only`)
  - Dirty repos: never auto-updated (you’ll be asked to commit/stash first)

See `help/CONFIGURATION.md` for the auto-update environment variables.

## Local URLs (stable)

Ports are fixed to avoid collisions:

- **Moovent Stack UI (control)**: `http://127.0.0.1:7000` (macOS note: `localhost:7000` may be claimed by AirPlay/AirTunes)
- **MQTT UI** (`mqtt-admin-dashboard`): `http://localhost:3000`
- **Dashboard UI** (`dashboard` client): `http://localhost:4000`
- **Backend API** (`mqtt_dashboard_watch`): `http://localhost:8000`

## Secrets model (dev vs prod)

### Local development (dev)

- `moovent-stack` **does not write** `INFISICAL_CLIENT_ID` or `INFISICAL_CLIENT_SECRET` to disk in `.env`
- Instead, it injects them into the process environment when launching `run_local_stack.py`

### Production (Render)

- Set `INFISICAL_CLIENT_ID` and `INFISICAL_CLIENT_SECRET` as **Render environment variables**

