# Moovent Stack

**Local dev stack launcher for Moovent developers.**

> New here? Read this top to bottom — it covers everything you need to go from zero to a running local stack.

---

## Before you install — what you need to request

`moovent-stack` is access-controlled. You need two things before the install works:

### 1. Infisical Machine Identity (ask your admin)

Ask a team admin to create a **Machine Identity** for you in Infisical and send you:

```
INFISICAL_CLIENT_ID=<your-client-id>
INFISICAL_CLIENT_SECRET=<your-client-secret>
```

Keep these private. Do not commit them, do not share them.

### 2. GitHub access (ask your admin)

Ask a team admin to add your GitHub account to the **Moovent GitHub organisation** and grant access to:
- `mqtt_dashboard_watch`
- `dashboard`

---

## Prerequisites

Install these on your Mac before anything else:

```bash
# Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/sh)"

# Node.js via nvm (recommended)
brew install nvm
nvm install 20 && nvm use 20

# Python 3.11+
brew install python@3.11

# GitHub CLI
brew install gh
```

Verify:
```bash
node --version    # v20.x
python3 --version # 3.11+
gh --version
```

---

## Install

```bash
brew tap moovent/tap
brew install moovent/tap/moovent-stack
```

Verify:
```bash
moovent-stack --version
```

---

## First run

```bash
moovent-stack
```

A setup page opens automatically in your browser at **`http://127.0.0.1:9000`**. Follow the three steps:

| Step | What it does |
|------|-------------|
| **1 — Infisical** | Enter your Client ID + Secret. Credentials are verified against the Moovent project. |
| **2 — Workspace + GitHub** | Choose where repos will be cloned (default: `~/Documents/Moovent-stack`). Authorise GitHub via OAuth. |
| **3 — Repos + branches** | Select which repos to clone (`mqtt_dashboard_watch`, `dashboard`) and which branch. Click **Install Selected**. |

After setup completes, the **Admin Dashboard** starts and your stack is running. All secrets are fetched from Infisical automatically — nothing sensitive is stored on disk.

---

## Daily usage

```bash
moovent-stack
```

That's it. Setup only runs once. On subsequent runs the stack starts directly.

---

## Local URLs

| Service | URL |
|---------|-----|
| Admin Dashboard | http://127.0.0.1:9000 |
| Dashboard UI | http://localhost:4000 |
| Backend API | http://localhost:5001 |
| MQTT UI | http://localhost:3000 |
| MQTT Backend | http://localhost:8000 |

> Use `127.0.0.1` (not `localhost`) for the Admin Dashboard — `localhost:9000` can conflict with AirPlay on macOS.

---

## Updating a service

The Admin Dashboard shows an **Update available** banner when a repo has new commits.

- If the repo is **clean**: click **Update** — it pulls and restarts automatically.
- If the repo has **unsaved work**: inline **Commit** and **Discard** buttons appear so you can resolve your state first.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `brew: formula not found` | Run `brew tap moovent/tap` first |
| Infisical credentials rejected | Check your Client ID/Secret with admin; ensure Machine Identity has project access |
| GitHub OAuth fails | Ensure your GitHub account is in the Moovent org |
| Port already in use | Something else is on 9000 / 5001 / 4000 / 8000 — stop conflicting processes |
| Stack starts but services crash | Check Admin Dashboard logs for the failing service |

Full troubleshooting: [`help/TROUBLESHOOTING.md`](help/TROUBLESHOOTING.md)

---

## Documentation

| File | Contents |
|------|----------|
| [`help/GETTING_STARTED.md`](help/GETTING_STARTED.md) | Full onboarding walkthrough |
| [`help/CONFIGURATION.md`](help/CONFIGURATION.md) | All env vars and config options |
| [`help/TROUBLESHOOTING.md`](help/TROUBLESHOOTING.md) | Common issues and fixes |
| [`help/SECURITY.md`](help/SECURITY.md) | Secrets model and security notes |
| [`help/DEVELOPMENT.md`](help/DEVELOPMENT.md) | For contributors to moovent-stack itself |
| [`CHANGELOG.md`](CHANGELOG.md) | Release history |

---

## For contributors

Run locally (no Homebrew install needed):

```bash
git clone https://github.com/Moovent/moovent-stack.git
cd moovent-stack
python3 -m moovent_stack
```

See [`help/DEVELOPMENT.md`](help/DEVELOPMENT.md) for the full contributor guide.
