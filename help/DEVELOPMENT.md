# Development — Moovent Stack

This page is for contributors working on the `moovent-stack` Python package.

## Run locally

From the repo root:

```bash
python3 -m moovent_stack
```

Notes:
- The launcher opens a local setup UI if required config is missing.
- If the default setup port is already in use, set `MOOVENT_SETUP_PORT`.

## Module layout

Core logic is split into focused modules:

- `moovent_stack/app.py`: main orchestration flow.
- `moovent_stack/config.py`: constants + env helpers.
- `moovent_stack/storage.py`: config/cache persistence.
- `moovent_stack/infisical.py`: Infisical auth + scope.
- `moovent_stack/github.py`: GitHub OAuth + API calls.
- `moovent_stack/workspace.py`: repo cloning + workspace validation.
- `moovent_stack/runner.py`: runtime env injection + runner.
- `moovent_stack/access.py`: access cache + enforcement.
- `moovent_stack/setup/`: setup UI assets, templates, and HTTP server.

## Tests

```bash
python3 -m unittest
```

## Formatting

This repo uses `ruff` + `black` (when available in your environment).

Typical workflow:

```bash
ruff check --fix .
black .
python3 -m unittest
```

## Release checklist (high level)

- Update `VERSION`
- Update `CHANGELOG.md`
- Build release artifact (`scripts/build_release.py`)
- Create GitHub release + upload artifact
- Update Homebrew formula to point at the new release asset

