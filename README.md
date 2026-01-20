# Moovent Stack (Internal)

This repository contains the **Moovent developer stack launcher**.

Goal: the easiest possible onboarding for non-technical users:
- Install with **one command** via Homebrew
- Run with **one command** (`moovent-stack`)
- Uses local `.env` files (local-only mode)
- Access is controlled via Infisical Universal Auth

## Install (Homebrew)

```bash
brew install moovent/tap/moovent-stack
```

## Run

If Infisical credentials or workspace are not configured, `moovent-stack` opens a setup page automatically.
You can also set it manually:

```bash
export INFISICAL_CLIENT_ID="YOUR_CLIENT_ID"
export INFISICAL_CLIENT_SECRET="YOUR_CLIENT_SECRET"
export INFISICAL_HOST="https://app.infisical.com" # optional override
export MOOVENT_GITHUB_CLIENT_ID="YOUR_GITHUB_OAUTH_CLIENT_ID"
export MOOVENT_GITHUB_CLIENT_SECRET="YOUR_GITHUB_OAUTH_CLIENT_SECRET"
export MOOVENT_SETUP_PORT=9010 # should match GitHub OAuth callback
export MOOVENT_WORKSPACE_ROOT="/Users/you/Projects/moovent"  # contains run_local_stack.py
moovent-stack
```

## Local-only mode (default)

The CLI launches the local stack by running `run_local_stack.py` from your workspace.

Workspace requirements:
- `run_local_stack.py` at the workspace root
- `mqtt_dashboard_watch/` repo folder
- `dashboard/` repo folder

## Access control (Infisical Universal Auth)

On every run, the CLI authenticates using **Infisical Universal Auth** (cached with TTL).
If credentials are valid, access is allowed.

Env vars:

```bash
# Required:
INFISICAL_CLIENT_ID=...
INFISICAL_CLIENT_SECRET=...
# Optional (default: https://app.infisical.com, EU: https://eu.infisical.com):
INFISICAL_HOST=...
# GitHub OAuth (required for repo/branch setup):
MOOVENT_GITHUB_CLIENT_ID=...
MOOVENT_GITHUB_CLIENT_SECRET=...
MOOVENT_ACCESS_TTL_S=86400
MOOVENT_ACCESS_CACHE_PATH=~/.moovent_stack_access.json
MOOVENT_ACCESS_SELF_CLEAN=1
MOOVENT_SETUP_PORT=9010
# If set, disable setup page and fail fast when missing config:
MOOVENT_SETUP_NONINTERACTIVE=1
# Optional: override runner path directly
MOOVENT_RUNNER_PATH=/full/path/to/run_local_stack.py
# Optional: provide workspace root instead
MOOVENT_WORKSPACE_ROOT=/Users/you/Projects/moovent
```

## Development

Run locally:

```bash
python3 -m moovent_stack
```

