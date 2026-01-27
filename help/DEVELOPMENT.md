# Development — Moovent Stack

This page is for contributors working on the `moovent-stack` Python package.

## Run locally

From the repo root:

```bash
python3 -m moovent_stack
```

Or run the admin module directly with a workspace path:

```bash
python3 -m moovent_stack.admin /path/to/workspace
```

Notes:
- The launcher opens a local setup UI if required config is missing.
- If the default port (9000) is already in use, set `MOOVENT_SETUP_PORT`.

## Module layout

```
moovent_stack/
├── __init__.py
├── __main__.py          # Entry point for `python -m moovent_stack`
├── app.py               # Main orchestration (setup flow → admin module)
├── config.py            # Constants + env helpers
├── storage.py           # Config/cache persistence (~/.moovent_stack_*.json)
├── infisical.py         # Infisical auth + scope validation
├── github.py            # GitHub OAuth + API calls
├── workspace.py         # Repo cloning + workspace validation
├── runner.py            # Runtime env injection
├── access.py            # Access cache + enforcement
├── log.py               # File-based logging
│
├── setup/               # Setup UI (first-run wizard)
│   ├── __init__.py
│   ├── server.py        # HTTP server for setup pages
│   └── templates.py     # HTML templates (Step 1, 2, 3, etc.)
│
└── admin/               # Admin Dashboard (main UI after setup)
    ├── __init__.py      # Entry point: main(workspace)
    ├── __main__.py      # Allows `python -m moovent_stack.admin`
    ├── config.py        # Dashboard config (ports, env helpers)
    ├── logs.py          # LogEntry, LogStore (ring buffers, SSE)
    ├── services.py      # ServiceSpec, StackManager (start/stop/restart)
    ├── git_ops.py       # Git operations, GitCache
    ├── github.py        # GitHub OAuth helpers, GitHubState
    ├── access.py        # Infisical access validation
    ├── updates.py       # UpdateState (auto-pull, one-click update)
    ├── deps.py          # Dependency management (npm, pip, venv)
    ├── server.py        # HTTP server + API endpoints + SSE
    └── templates/
        └── dashboard.html  # Full dashboard HTML/CSS/JS (~1700 lines)
```

## Key classes

### StackManager (`admin/services.py`)

Manages child processes for all services:

```python
manager = StackManager(workspace_root, log_store)
manager.start_all()           # Start all defined services
manager.stop("mqtt-backend")  # Stop a specific service
manager.restart("mqtt-ui")    # Stop + start
manager.status_snapshot()     # Get current status of all services
manager.stop_all()            # Graceful shutdown
```

### LogStore (`admin/logs.py`)

Per-service ring buffers with SSE support:

```python
log_store = LogStore(max_entries=500)
log_store.append("mqtt-backend", "info", "Server started on port 8000")
entries = log_store.get("mqtt-backend", since_id=100)
# SSE: log_store.wait_for_new(timeout=30)
```

### UpdateState (`admin/updates.py`)

Tracks update status and handles one-click pulls:

```python
update_state = UpdateState(workspace_root)
update_state.refresh()  # Check for updates
status = update_state.get_status()
# {"mqtt_dashboard_watch": {"behind": 3, "can_update": True, ...}}
update_state.run_update("mqtt_dashboard_watch")  # Fast-forward pull
```

## Tests

```bash
python3 -m unittest
```

All tests are in the `tests/` directory.

## Formatting

This repo uses `ruff` + `black` (when available in your environment).

Typical workflow:

```bash
ruff check --fix .
black .
python3 -m unittest
```

## Building a release

1. Bump version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Build sdist + wheel:

```bash
python -m venv .venv
source .venv/bin/activate
pip install build
python -m build
```

4. Create GitHub release + upload `dist/moovent_stack-X.Y.Z.tar.gz`

```bash
gh release create vX.Y.Z --title "vX.Y.Z" --notes "..." dist/moovent_stack-X.Y.Z.tar.gz
```

5. Update Homebrew formula:

```bash
# Get asset ID and SHA256
gh api repos/Moovent/moovent-stack/releases/tags/vX.Y.Z --jq '.assets[0].id'
shasum -a 256 dist/moovent_stack-X.Y.Z.tar.gz

# Update Formula/moovent-stack.rb with new asset ID, SHA256, version
```

## Adding a new service

1. Add `ServiceSpec` in `admin/services.py`:

```python
ServiceSpec(
    name="my-service",
    display="My Service",
    cwd=lambda root: root / "my-service",
    cmd=["npm", "run", "dev"],
    port=5000,
    critical=False,  # True = stop stack if this crashes
)
```

2. The service will automatically appear in the dashboard with start/stop/restart controls.

## Adding a new API endpoint

Edit `admin/server.py` and add a route in `_AdminHandler`:

```python
def do_GET(self):
    if self.path == "/api/my-endpoint":
        self._json_response({"data": "value"})
        return
    # ... existing routes
```

## Dashboard UI changes

Edit `admin/templates/dashboard.html`. The file contains:

- HTML structure
- Embedded CSS (in `<style>` tag)
- Embedded JavaScript (in `<script>` tag)

The dashboard uses vanilla JS with no build step for simplicity.
