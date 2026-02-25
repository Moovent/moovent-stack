# Troubleshooting — Moovent Stack

## Admin Dashboard won't start: "Address already in use"

You'll see:

- `[setup] Unable to start local setup server: [Errno 48] Address already in use`

**Common cause**: Port 9000 is already in use by another process.

Fix by changing the port:

```bash
export MOOVENT_SETUP_PORT=9001
moovent-stack
```

Or kill the existing process:

```bash
lsof -i :9000  # Find the PID
kill <PID>
```

## "Setup incomplete" / setup keeps reopening

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

## "[runner] run_local_stack.py not found …"

Fix by ensuring your workspace folder contains `run_local_stack.py` at the root.

Option A:

```bash
export MOOVENT_WORKSPACE_ROOT="$HOME/Documents/Moovent-stack"
```

Option B:

```bash
export MOOVENT_RUNNER_PATH="/full/path/to/run_local_stack.py"
```

## "Workspace missing: mqtt_dashboard_watch/, dashboard/ …"

Your workspace must contain these repo folders:

- `mqtt_dashboard_watch/` (only if selected in Step 3)
- `dashboard/` (only if selected in Step 3)

Fix:
- Re-run setup Step 3 and install the repos, or clone them manually into your workspace root.

## Services show "not listening" in the dashboard

**Common causes**:

1. **Service crashed on startup**: Check the logs panel in the dashboard for errors.
2. **Port already in use**: Another process is using the port.
3. **Missing dependencies**: npm install or pip install failed.
4. **Missing environment variables**: Required secrets not available.

**Debug steps**:

1. Click on the service card to expand logs
2. Look for error messages
3. Check if dependencies installed: `ls <workspace>/mqtt_dashboard_watch/.venv` or `node_modules`

Port behavior on recent versions:

- On service start, `moovent-stack` auto-cleans stale listeners from previous runs when
  the stale process belongs to the same repo path.
- If the port is occupied by an unrelated process, startup is blocked and the log shows
  blocking PID(s). In that case, stop that process manually or use the dashboard "Free port"
  action where available.

## "Update available" banner won't update

Common causes:

- **Dirty repo**: you have local changes (uncommitted files).
  - Fix: commit/stash/discard changes, then click **Update now** again.
- **Detached HEAD**: the repo is not on a branch (checked out to a commit).
  - Fix: checkout a branch (`git checkout main`) and retry.
- **Upstream missing**: `origin/<branch>` doesn't exist (non-standard branch or remote).
  - Fix: ensure `origin` points to the expected remote and the branch exists.
- **Fetch/pull failed**: network issues, auth issues, or GitHub rate limiting.
  - Fix: run `git fetch --prune origin` inside the repo and inspect the error.

Behavior:

- The updater only does **fast-forward pulls** (`--ff-only`).
- It never creates merge commits.

## Wrong UI showing on a port

### Expected layout

| Port | Expected UI |
|------|-------------|
| 9000 | Admin Dashboard (service control, logs) |
| 3000 | MQTT Admin UI |
| 4000 | Dashboard client |
| 8000 | Backend API |

### I see the old control page instead of the full dashboard

**Cause**: You're running an old version of `moovent-stack`.

**Fix**:

```bash
brew reinstall moovent-stack
pkill -f moovent_stack  # Kill any running instances
moovent-stack
```

### localhost:3000 shows MQTT UI but I expected Dashboard

The MQTT Admin UI runs on port 3000. The Dashboard client runs on port 4000.

Fix:
- Open `http://127.0.0.1:9000` for the Admin Dashboard with all links
- Open `http://localhost:4000` for the Dashboard client

## GitHub connect issues (403 / scopes / SSO)

Symptoms:
- Step 3 shows repo/branch fetch errors
- Dashboard shows "GitHub not connected"
- You're asked to reconnect repeatedly

Common causes:
- Token expired
- Missing scopes (the launcher requests `repo read:org`)
- Org SSO enforcement requires authorizing the token

Fix:
- In the Admin Dashboard, click the GitHub settings button to reconnect
- If your org enforces SSO, authorize the app/token in GitHub
- If the problem persists, contact your admin to confirm the OAuth app + scopes

## Infisical access denied

You may see messages like:

- `Infisical access check failed. Reason: http_403`
- `project_id_mismatch`

Fix:
- Confirm your Machine Identity is granted access to the Moovent project
- Ensure you're using the correct Infisical tenant:
  - EU: `https://eu.infisical.com`
  - US: `https://app.infisical.com`

Override host if needed:

```bash
export INFISICAL_HOST="https://eu.infisical.com"
```

## Infisical unreachable

Current behavior is fail-closed after cache expiry:

- If Infisical cannot be reached and the cache entry is expired, access is denied.
- If you need to revalidate from scratch, delete `~/.moovent_stack_access.json`
  (or your custom `MOOVENT_ACCESS_CACHE_PATH`) and retry.

## How to completely reset moovent-stack

Remove all config and cache files:

```bash
rm ~/.moovent_stack_config.json
rm ~/.moovent_stack_access.json
rm ~/.moovent_stack.log
rm ~/.moovent_stack_admin.log
```

Then re-run:

```bash
moovent-stack
```

This will start fresh setup from Step 1.

## Logs are empty in the dashboard

**Cause**: The service isn't running or crashed immediately.

**Debug**:

1. Check if the service is "listening" (green indicator)
2. Click Start to restart the service
3. Check terminal output where you ran `moovent-stack`
4. Check log files: `~/.moovent_stack.log`, `~/.moovent_stack_admin.log`

## npm/pip install fails

**Common causes**:

1. **Network issues**: Check internet connection
2. **npm/node not installed**: Install Node.js
3. **Python venv issues**: Delete `.venv` folder and restart

**Fix**:

```bash
# For Node issues
cd <workspace>/mqtt_dashboard_watch/mqtt-admin-dashboard
rm -rf node_modules
npm install

# For Python issues
cd <workspace>/mqtt_dashboard_watch
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then restart the Admin Dashboard.
