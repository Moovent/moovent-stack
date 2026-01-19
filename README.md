# Moovent Stack (Internal)

This repository contains the **Moovent developer stack launcher**.

Goal: the easiest possible onboarding for non-technical users:
- Install with **one command** via Homebrew
- Run with **one command** (`moovent-stack`)
- No local `.env` files required (remote-only mode)
- Access can be revoked centrally (runtime access checks)

## Install (Homebrew)

```bash
brew install moovent/tap/moovent-stack
```

## Run

If access is not configured, `moovent-stack` will open a setup page automatically.
You can also set it manually:

```bash
export MOOVENT_ACCESS_URL="https://YOUR-INTERNAL-ACCESS-ENDPOINT"
export MOOVENT_ACCESS_TOKEN="YOUR_TOKEN"   # optional, if your access API requires it
moovent-stack
```

## Remote-only mode (recommended)

Remote-only mode opens the hosted stack (Render) and does **not** start any local services.
This keeps secrets server-side and prevents engineers from needing `.env` files locally.

```bash
export MOOVENT_REMOTE_MODE=1
export MOOVENT_REMOTE_URL="https://moovent-frontend.onrender.com"
export MOOVENT_REMOTE_BACKEND_URL="https://moovent-backend.onrender.com"
moovent-stack
```

Optional:

```bash
export MOOVENT_REMOTE_OPEN_BROWSER=0
```

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
```

## Development

Run locally:

```bash
python3 -m moovent_stack
```

