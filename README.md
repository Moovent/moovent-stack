# Moovent Stack (Internal)

This repository contains the **Moovent developer stack launcher**.

Goal: the easiest possible onboarding for non-technical users:
- Install with **one command** via Homebrew
- Run with **one command** (`moovent-stack`)
- Uses local `.env` files (local-only mode)
- Access can be revoked centrally (runtime access checks)

## Install (Homebrew)

```bash
brew install moovent/tap/moovent-stack
```

## Run

If access or workspace is not configured, `moovent-stack` opens a setup page automatically.
You can also set it manually:

```bash
export MOOVENT_ACCESS_URL="https://YOUR-INTERNAL-ACCESS-ENDPOINT"
export MOOVENT_ACCESS_TOKEN="YOUR_TOKEN"   # optional, if your access API requires it
export MOOVENT_WORKSPACE_ROOT="/Users/you/Projects/moovent"  # contains run_local_stack.py
moovent-stack
```

## Local-only mode (default)

The CLI launches the local stack by running `run_local_stack.py` from your workspace.

Workspace requirements:
- `run_local_stack.py` at the workspace root
- `mqtt_dashboard_watch/` repo folder
- `dashboard/` repo folder

## Access control & revocation

On every run, the CLI checks access via `MOOVENT_ACCESS_URL` (cached with TTL).

Recommended access API response (JSON):

```json
{
  "allowed": true,
  "reason": "optional string",
  "cleanup": false
}
```

If `allowed=false`, the CLI blocks usage. If `cleanup=true` and self-clean is enabled, the CLI will remove its own Homebrew install on next run.

Env vars:

```bash
# Required:
MOOVENT_ACCESS_URL=...
# Optional:
MOOVENT_ACCESS_TOKEN=...
MOOVENT_ACCESS_TTL_S=86400
MOOVENT_ACCESS_CACHE_PATH=~/.moovent_stack_access.json
MOOVENT_ACCESS_SELF_CLEAN=1
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

