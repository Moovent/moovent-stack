# Getting Started — Moovent Stack

`moovent-stack` is a **local stack launcher** that:

- Validates access using **Infisical Universal Auth** (Machine Identity)
- Helps you choose a **workspace install path**
- Connects to GitHub via OAuth and clones the Moovent repos you select
- Fetches all runtime secrets from Infisical and injects them into services
- Runs your local stack via the **Admin Dashboard**

---

## New Developer Onboarding (start here)

Follow these steps in order. Steps 1–3 require admin action.

### Step 0 — Prerequisites

Install these before anything else:

```bash
# Homebrew (macOS package manager)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/sh)"

# Node.js (via nvm — recommended)
brew install nvm
nvm install 20
nvm use 20

# Python 3.11+
brew install python@3.11

# Git
brew install git

# GitHub CLI (used by moovent-stack for OAuth)
brew install gh
```

Verify:
```bash
node --version    # v20.x
python3 --version # 3.11+
git --version
gh --version
```

---

### Step 1 — Request Infisical access (admin action required)

Ask your team admin to:

1. Create a **Machine Identity** for you in Infisical
   - Go to **Infisical → Project → Access → Machine Identities → Add**
   - Assign it **read** access to the Moovent project (EU: `https://eu.infisical.com`)
2. Send you the **Client ID** and **Client Secret** for that identity

You will receive two values:
```
INFISICAL_CLIENT_ID=<your-client-id>
INFISICAL_CLIENT_SECRET=<your-client-secret>
```

> Keep these private. Do not commit them to git. Do not share them.

---

### Step 2 — Request GitHub access (admin action required)

Ask your team admin to:

1. Add your GitHub account to the **Moovent GitHub organisation**
2. Grant access to the relevant repositories (`mqtt_dashboard_watch`, `dashboard`)

---

### Step 3 — Install moovent-stack

```bash
brew tap moovent/tap
brew install moovent/tap/moovent-stack
```

Verify:
```bash
moovent-stack --version
```

---

### Step 4 — Run for the first time

```bash
moovent-stack
```

A setup page opens automatically at **`http://127.0.0.1:9000`**. Follow the three steps below.

---

## Setup flow (what you'll see on first run)

### Step 1 — Infisical access

- Enter your **Infisical Client ID** and **Client Secret** (from Step 1 above)
- `moovent-stack` verifies your credentials against the required Moovent project
- If valid, you proceed; if not, you'll see an error message

Notes:
- Default host is **EU**: `https://eu.infisical.com`
- You can override with `INFISICAL_HOST` env var

### Step 2 — Workspace + GitHub

- Choose **Workspace Install Path**
  - Default: `~/Documents/Moovent-stack`
  - This is where repos will be cloned
- Click **Connect GitHub**
  - Your browser opens for GitHub OAuth authorisation
  - After approving, moovent-stack stores a GitHub access token locally

Admin note:
- GitHub OAuth credentials are fetched from Infisical (admin-provisioned). If missing, the UI shows "Contact your admin".

### Step 3 — Repo + branch selection

- Toggle which repos to install:
  - `mqtt_dashboard_watch` — MQTT backend service
  - `dashboard` — Event management web app
- Pick a branch per repo (default: `main`)
- Click **Install Selected**

After cloning:
- `moovent-stack` writes **only non-sensitive Infisical scope config** (no secrets) to:
  - `mqtt_dashboard_watch/.env`
  - `dashboard/server/.env` (if dashboard repo selected)
- The Admin Dashboard starts at `http://127.0.0.1:9000`

> **You're done.** All secrets are fetched from Infisical at runtime — nothing sensitive is on disk.

## After first run — daily usage

Once setup is complete, just run:

```bash
moovent-stack
```

That's it. The stack starts, secrets are injected, services come up.

---

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

## Secrets model

### Local development

- `moovent-stack` **never writes** `INFISICAL_CLIENT_ID` or `INFISICAL_CLIENT_SECRET` to disk
- It fetches all runtime secrets from Infisical and injects them directly into service processes
- `.env` files in each repo contain **only non-sensitive Infisical scope config** (project ID, environment, host)

### Production (Digital Ocean Droplet)

- The dashboard server runs standalone (no moovent-stack)
- An `INFISICAL_SERVICE_TOKEN` is stored in `/var/www/moovent_webapp/.env` on the Droplet (gitignored, `chmod 600`)
- The server's `infisical.js` bootstrap fetches all secrets from Infisical at container startup
- See `dashboard/help/DEPLOYMENT.md` for the full Droplet setup

---

## Troubleshooting first install

| Problem | Fix |
|---------|-----|
| `brew: formula not found` | Run `brew tap moovent/tap` first |
| Infisical credentials rejected | Check Client ID/Secret with admin; ensure Machine Identity has project access |
| GitHub OAuth fails | Ensure your GitHub account is in the Moovent org |
| Repos fail to clone | Check GitHub access with admin |
| Port already in use | Something else is on 9000/8000/4000/3000 — stop conflicting processes |

For more: see `help/TROUBLESHOOTING.md`
