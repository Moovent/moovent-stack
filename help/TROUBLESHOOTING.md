# Troubleshooting — Moovent Stack

## Setup server won’t start: “Address already in use”

You’ll see:

- `[setup] Unable to start local setup server: [Errno 48] Address already in use`

Fix by changing the port:

```bash
export MOOVENT_SETUP_PORT=7001
moovent-stack
```

## “Setup incomplete” / setup keeps reopening

`moovent-stack` starts the setup UI when any of these are missing:

- Infisical client id/secret
- workspace path
- GitHub access token (from Connect GitHub)

Fix:
- Re-run `moovent-stack` and finish all steps.

If you want it to fail fast instead of opening the UI:

```bash
export MOOVENT_SETUP_NONINTERACTIVE=1
moovent-stack
```

## “[runner] run_local_stack.py not found …”

Fix by ensuring your workspace folder contains `run_local_stack.py` at the root.

Option A:

```bash
export MOOVENT_WORKSPACE_ROOT="$HOME/Documents/Moovent-stack"
```

Option B:

```bash
export MOOVENT_RUNNER_PATH="/full/path/to/run_local_stack.py"
```

## “Workspace missing: mqtt_dashboard_watch/, dashboard/ …”

Your workspace must contain these repo folders:

- `mqtt_dashboard_watch/` (only if selected in Step 3)
- `dashboard/` (only if selected in Step 3)

Fix:
- Re-run setup Step 3 and install the repos, or clone them manually into your workspace root.

## “Update available” banner won’t update

Common causes:

- **Dirty repo**: you have local changes (uncommitted files).
  - Fix: commit/stash/discard changes, then click **Update now** again.
- **Detached HEAD**: the repo is not on a branch (checked out to a commit).
  - Fix: checkout a branch (`git checkout main`) and retry.
- **Upstream missing**: `origin/<branch>` doesn’t exist (non-standard branch or remote).
  - Fix: ensure `origin` points to the expected remote and the branch exists.
- **Fetch/pull failed**: network issues, auth issues, or GitHub rate limiting.
  - Fix: run `git fetch --prune origin` inside the repo and inspect the error.

Behavior:

- The updater only does **fast-forward pulls** (`--ff-only`).
- It never creates merge commits.

## I expected the dashboard but localhost:3000 shows the MQTT UI

Behavior:

- `http://localhost:3000` is the MQTT admin UI (when mqtt is installed).
- `http://localhost:4000` is the dashboard client (when dashboard is installed).
- `http://localhost:7000` is the Moovent Stack control page (always).

Fix:

- Open `http://localhost:7000` to see the Moovent Stack links.
- Or open `http://localhost:4000` directly for the dashboard client.

## GitHub connect issues (403 / scopes / SSO)

Symptoms:
- Step 3 shows repo/branch fetch errors
- You’re asked to reconnect repeatedly

Common causes:
- Token expired
- Missing scopes (the launcher requests `repo read:org`)
- Org SSO enforcement requires authorizing the token

Fix:
- Go back to Step 2 and click **Connect** again
- If your org enforces SSO, authorize the app/token in GitHub
- If the problem persists, contact your admin to confirm the OAuth app + scopes

## Infisical access denied

You may see messages like:

- `Infisical access check failed. Reason: http_403`
- `project_id_mismatch`

Fix:
- Confirm your Machine Identity is granted access to the Moovent project
- Ensure you’re using the correct Infisical tenant:
  - EU: `https://eu.infisical.com`
  - US: `https://app.infisical.com`

Override host if needed:

```bash
export INFISICAL_HOST="https://eu.infisical.com"
```

## Infisical unreachable (but you were previously allowed)

If Infisical can’t be reached and you have a valid cached allow entry, `moovent-stack` may continue using the cache.

To force a fresh check:
- delete `~/.moovent_stack_access.json` (or your custom `MOOVENT_ACCESS_CACHE_PATH`)

