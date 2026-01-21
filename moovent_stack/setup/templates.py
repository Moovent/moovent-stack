"""
HTML templates for the setup flow.
"""

from __future__ import annotations

from typing import Optional

from ..config import __version__, _current_year
from ..workspace import _default_workspace_path
from .assets import (
    MOOVENT_ACCENT,
    MOOVENT_BACKGROUND,
    MOOVENT_BLUE,
    MOOVENT_GREEN,
    MOOVENT_LOGO_BASE64,
    MOOVENT_TEAL,
)
from ..config import (
    REQUIRED_INFISICAL_ORG_ID,
    REQUIRED_INFISICAL_PROJECT_ID,
    DEFAULT_INFISICAL_ENVIRONMENT,
)


def _setup_steps_html(current_step: int) -> str:
    """Render the step list group (from help/tailwind set-up flows)."""
    steps = [
        "Infisical credentials",
        "GitHub + install path",
        "Repo + branch selection",
    ]
    items = []
    for idx, label in enumerate(steps, start=1):
        if idx < current_step:
            icon = (
                '<span class="size-5 flex shrink-0 justify-center items-center '
                'bg-teal-600 text-white rounded-full">'
                '<svg class="shrink-0 size-3.5" xmlns="http://www.w3.org/2000/svg" '
                'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
                'stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"></path></svg>'
                "</span>"
            )
            text = f'<s class="text-sm text-gray-400">{label}</s>'
        elif idx == current_step:
            icon = (
                '<span class="size-5 flex shrink-0 justify-center items-center '
                'border border-dashed border-gray-300 text-gray-500 rounded-full">'
                f'<span class="text-[11px]">{idx}</span></span>'
            )
            text = f'<span class="text-sm text-gray-800 font-medium">{label}</span>'
        else:
            icon = (
                '<span class="size-5 flex shrink-0 justify-center items-center '
                'border border-dashed border-gray-300 text-gray-500 rounded-full">'
                f'<span class="text-[11px]">{idx}</span></span>'
            )
            text = f'<span class="text-sm text-gray-600">{label}</span>'
        items.append(
            f"""
            <div class="py-2 px-2.5 flex items-center gap-x-3 bg-gray-100 rounded-lg">
              {icon}
              <div class="grow">{text}</div>
            </div>
            """
        )
    return f'<div class="space-y-1.5">{"".join(items)}</div>'


def _setup_shell(
    step_title: str,
    step_subtitle: str,
    step_index: int,
    step_total: int,
    content_html: str,
    error_text: str = "",
) -> str:
    """Render the shared setup shell."""
    error_block = ""
    if error_text:
        error_block = f"""
        <div class="mb-4 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          {error_text}
        </div>
        """

    progress_cells = []
    for i in range(1, step_total + 1):
        bar_class = "bg-teal-600" if i <= step_index else "bg-teal-600 opacity-30"
        progress_cells.append(
            f'<div class="{bar_class} h-2 flex-auto rounded-sm"></div>'
        )

    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Moovent Stack Setup</title>
    <link rel="icon" href="{MOOVENT_LOGO_BASE64}" />
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="text-gray-800" style="background-color: {MOOVENT_BACKGROUND};">
    <main class="min-h-screen flex items-center justify-center px-4 py-10">
      <div class="w-full max-w-xl">
        <div class="mb-6 text-center">
          <div class="mx-auto flex items-center justify-center">
            <img src="{MOOVENT_LOGO_BASE64}" alt="Moovent" class="h-16" />
          </div>
          <h1 class="mt-4 font-semibold text-2xl text-gray-800">Welcome to Moovent Stack</h1>
          <p class="mt-2 text-sm text-gray-500">
            Run the full Moovent development environment locally.<br/>
            Quick setup, then you're ready to code.
          </p>
        </div>

        <div class="relative overflow-hidden bg-white border border-gray-200 rounded-xl shadow-sm">
          <div class="p-5" style="background: linear-gradient(to right, {MOOVENT_BLUE}40, {MOOVENT_TEAL}40, {MOOVENT_GREEN}40);">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 class="font-semibold text-gray-800">{step_title}</h2>
                <p class="mt-1 text-xs text-gray-600">{step_subtitle}</p>
              </div>
              <span class="py-1 px-2 inline-flex items-center gap-x-1 text-xs font-semibold uppercase rounded-md text-white"
                style="background: linear-gradient(to top right, {MOOVENT_ACCENT}, #14b8a6);">
                Setup
              </span>
            </div>

            <div class="mt-4">
              <div class="flex items-center justify-between">
                <span class="text-xs text-gray-600">Step {step_index} of {step_total}</span>
                <span class="text-xs text-gray-600">{step_title}</span>
              </div>
              <div class="mt-2 grid grid-cols-{step_total} gap-x-1.5">
                {''.join(progress_cells)}
              </div>
            </div>
          </div>

          <div class="p-5 space-y-5">
            {error_block}
            {content_html}
          </div>
        </div>

        <div class="mt-4 p-4 bg-white border border-gray-200 rounded-xl">
          <h3 class="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">Setup steps</h3>
          {_setup_steps_html(step_index)}
        </div>

        <p class="mt-6 text-center text-xs text-gray-500">
          Need help? Contact your team lead or check the
          <a href="https://github.com/Moovent/moovent-stack/blob/main/help/GETTING_STARTED.md" target="_blank"
            class="hover:underline" style="color: {MOOVENT_ACCENT};">Moovent Stack docs</a>.
        </p>
      </div>
    </main>

    <footer class="py-6 text-center">
      <p class="text-xs text-gray-400">
        &copy; {_current_year()} Moovent. All rights reserved.
        <span class="mx-1.5">&middot;</span>
        <span class="text-gray-300">v{__version__}</span>
      </p>
    </footer>
  </body>
</html>
""".strip()


def _setup_step1_html(error_text: str = "") -> str:
    """Step 1: Infisical credentials only."""
    content = f"""
    <form class="space-y-5" method="POST" action="/save-step1">
      <div>
        <label class="block mb-2 text-sm font-medium text-gray-800">
          Infisical Client ID <span class="text-red-500">*</span>
        </label>
        <input
          name="client_id"
          required
          autocomplete="username"
          placeholder="infisical_client_id_xxx"
          class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{MOOVENT_ACCENT}]/50 focus:border-[{MOOVENT_ACCENT}]"
        />
      </div>

      <div>
        <label class="block mb-2 text-sm font-medium text-gray-800">
          Infisical Client Secret <span class="text-red-500">*</span>
        </label>
        <input
          name="client_secret"
          type="password"
          required
          autocomplete="current-password"
          placeholder="infisical_client_secret_xxx"
          class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{MOOVENT_ACCENT}]/50 focus:border-[{MOOVENT_ACCENT}]"
        />
        <p class="mt-2 text-xs text-gray-500">
          Stored locally with restricted permissions. Default host: eu.infisical.com (set INFISICAL_HOST to override).
        </p>
      </div>

      <div class="p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <p class="text-xs text-gray-500 mb-1">Access scope</p>
        <p class="text-sm text-gray-800">
          Org: <span class="font-mono text-xs">{REQUIRED_INFISICAL_ORG_ID}</span><br/>
          Project: <span class="font-mono text-xs">{REQUIRED_INFISICAL_PROJECT_ID}</span><br/>
          Env: <span class="font-mono text-xs">{DEFAULT_INFISICAL_ENVIRONMENT}</span>
        </p>
        <p class="mt-2 text-xs text-gray-500">
          We verify your credentials can access this project before continuing.
        </p>
      </div>

      <div class="pt-2">
        <button
          type="submit"
          class="py-3 px-4 w-full inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-transparent text-white hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2"
          style="background-color: {MOOVENT_ACCENT}; --tw-ring-color: {MOOVENT_ACCENT};"
        >
          Continue
          <svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M12 5l7 7-7 7"/></svg>
        </button>
      </div>
    </form>
    """
    return _setup_shell(
        "Infisical access",
        "Sign in with your Infisical Universal Auth credentials",
        1,
        3,
        content,
        error_text,
    )


def _setup_step2_html(
    github_login: Optional[str],
    error_text: str = "",
    workspace_root: str = "",
    oauth_ready: bool = True,
) -> str:
    """Step 2: GitHub OAuth + install path."""
    # Use default if not provided
    if not workspace_root:
        workspace_root = _default_workspace_path()

    status = (
        f'<span class="inline-flex items-center gap-2 text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-1 rounded-md">Connected as {github_login}</span>'
        if github_login
        else '<span class="text-xs text-gray-500">Not connected yet</span>'
    )
    oauth_hint = (
        ""
        if oauth_ready
        else "<p class='text-xs text-red-600 mt-2'>GitHub OAuth not configured. Contact your admin.</p>"
    )

    content = f"""
    <form class="space-y-5" method="POST" action="/save-step2">
      <div>
        <label class="block mb-2 text-sm font-medium text-gray-800">
          Workspace Install Path <span class="text-red-500">*</span>
        </label>
        <input
          name="workspace_root"
          required
          autocomplete="off"
          placeholder="{_default_workspace_path()}"
          value="{workspace_root}"
          class="py-3 px-4 block w-full bg-white border border-gray-200 rounded-lg text-sm text-gray-800 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-[{MOOVENT_ACCENT}]/50 focus:border-[{MOOVENT_ACCENT}]"
        />
        <p class="mt-2 text-xs text-gray-500">Repos will be cloned into this folder.</p>
      </div>

      <div class="p-4 bg-gray-50 border border-gray-200 rounded-lg">
        <div class="flex items-center justify-between gap-3">
          <div>
            <p class="text-sm font-medium text-gray-800">Connect GitHub</p>
            <p class="text-xs text-gray-500">Authorize Moovent Stack to access your repos.</p>
          </div>
          <a href="/oauth/start" class="py-2 px-3 inline-flex items-center gap-x-2 text-xs font-medium rounded-lg border border-gray-200 bg-white text-gray-800 hover:bg-gray-50">
            Connect
          </a>
        </div>
        <div class="mt-2">{status}</div>
        {oauth_hint}
      </div>

      <div class="pt-2">
        <button
          type="submit"
          class="py-3 px-4 w-full inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-transparent text-white hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2"
          style="background-color: {MOOVENT_ACCENT}; --tw-ring-color: {MOOVENT_ACCENT};"
        >
          Continue
          <svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M5 12h14M12 5l7 7-7 7"/></svg>
        </button>
      </div>
    </form>
    """
    return _setup_shell(
        "GitHub + install path",
        "Authorize GitHub and choose where repos will be installed",
        2,
        3,
        content,
        error_text,
    )


def _setup_step3_html(
    mqtt_branches: list[str],
    dashboard_branches: list[str],
    error_text: str = "",
) -> str:
    """Step 3: Repo + branch selection with card-based UI.

    Each repo is a card with:
    - Toggle to enable/disable installation
    - Branch dropdown (only when enabled)
    - Only shows repos the user has access to
    """
    # Build repo cards - only show repos the user can access
    cards_html = ""

    # mqtt_dashboard_watch card
    if mqtt_branches:
        mqtt_options = "\n".join(
            [
                f"<option value='{b}' {'selected' if b == 'main' else ''}>{b}</option>"
                for b in mqtt_branches
            ]
        )
        cards_html += f"""
      <div class="p-4 bg-white border border-gray-200 rounded-xl">
        <div class="flex items-start gap-x-4">
          <!-- Repo icon -->
          <div class="shrink-0 flex items-center justify-center w-10 h-10 bg-gray-100 text-gray-600 rounded-lg">
            <svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 9.776c.112-.017.227-.026.344-.026h15.812c.117 0 .232.009.344.026m-16.5 0a2.25 2.25 0 0 0-1.883 2.542l.857 6a2.25 2.25 0 0 0 2.227 1.932H19.05a2.25 2.25 0 0 0 2.227-1.932l.857-6a2.25 2.25 0 0 0-1.883-2.542m-16.5 0V6A2.25 2.25 0 0 1 6 3.75h3.879a1.5 1.5 0 0 1 1.06.44l2.122 2.12a1.5 1.5 0 0 0 1.06.44H18A2.25 2.25 0 0 1 20.25 9v.776"/>
            </svg>
          </div>

          <!-- Content -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center justify-between gap-x-3">
              <div>
                <h3 class="text-sm font-semibold text-gray-800">mqtt_dashboard_watch</h3>
                <p class="mt-0.5 text-xs text-gray-500">Backend service for MQTT monitoring</p>
              </div>
              <!-- Toggle -->
              <label class="relative inline-block w-11 h-6 cursor-pointer shrink-0">
                <input type="checkbox" name="install_mqtt" value="1" class="peer sr-only" checked onchange="toggleRepoCard(this, 'mqtt-branch-select')"/>
                <span class="absolute inset-0 bg-gray-200 rounded-full transition-colors duration-200 ease-in-out peer-checked:bg-[{MOOVENT_ACCENT}]"></span>
                <span class="absolute top-1/2 start-0.5 -translate-y-1/2 w-5 h-5 bg-white rounded-full shadow-sm transition-transform duration-200 ease-in-out peer-checked:translate-x-full"></span>
              </label>
            </div>

            <!-- Branch select (only visible when enabled) -->
            <div id="mqtt-branch-select" class="mt-3 pt-3 border-t border-gray-100">
              <label class="block text-xs font-medium text-gray-600 mb-1.5">Branch</label>
              <select name="mqtt_branch" class="py-2 px-3 block w-full bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-[{MOOVENT_ACCENT}]/30 focus:border-[{MOOVENT_ACCENT}]">
                {mqtt_options}
              </select>
            </div>
          </div>
        </div>
      </div>
        """

    # dashboard card
    if dashboard_branches:
        dash_options = "\n".join(
            [
                f"<option value='{b}' {'selected' if b == 'main' else ''}>{b}</option>"
                for b in dashboard_branches
            ]
        )
        cards_html += f"""
      <div class="p-4 bg-white border border-gray-200 rounded-xl">
        <div class="flex items-start gap-x-4">
          <!-- Repo icon -->
          <div class="shrink-0 flex items-center justify-center w-10 h-10 bg-gray-100 text-gray-600 rounded-lg">
            <svg class="w-5 h-5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 20.25h12m-7.5-3v3m3-3v3m-10.125-3h17.25c.621 0 1.125-.504 1.125-1.125V4.875c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125Z"/>
            </svg>
          </div>

          <!-- Content -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center justify-between gap-x-3">
              <div>
                <h3 class="text-sm font-semibold text-gray-800">dashboard</h3>
                <p class="mt-0.5 text-xs text-gray-500">Admin dashboard frontend</p>
              </div>
              <!-- Toggle -->
              <label class="relative inline-block w-11 h-6 cursor-pointer shrink-0">
                <input type="checkbox" name="install_dashboard" value="1" class="peer sr-only" checked onchange="toggleRepoCard(this, 'dashboard-branch-select')"/>
                <span class="absolute inset-0 bg-gray-200 rounded-full transition-colors duration-200 ease-in-out peer-checked:bg-[{MOOVENT_ACCENT}]"></span>
                <span class="absolute top-1/2 start-0.5 -translate-y-1/2 w-5 h-5 bg-white rounded-full shadow-sm transition-transform duration-200 ease-in-out peer-checked:translate-x-full"></span>
              </label>
            </div>

            <!-- Branch select (only visible when enabled) -->
            <div id="dashboard-branch-select" class="mt-3 pt-3 border-t border-gray-100">
              <label class="block text-xs font-medium text-gray-600 mb-1.5">Branch</label>
              <select name="dashboard_branch" class="py-2 px-3 block w-full bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-[{MOOVENT_ACCENT}]/30 focus:border-[{MOOVENT_ACCENT}]">
                {dash_options}
              </select>
            </div>
          </div>
        </div>
      </div>
        """

    # Message when no repos are accessible
    if not cards_html:
        cards_html = """
      <div class="p-6 bg-amber-50 border border-amber-200 rounded-xl text-center">
        <svg class="mx-auto w-8 h-8 text-amber-500 mb-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"/>
        </svg>
        <p class="text-sm text-amber-800 font-medium">No accessible repositories</p>
        <p class="mt-1 text-xs text-amber-600">Your GitHub account doesn't have access to the Moovent repositories. Please contact an administrator.</p>
      </div>
        """

    content = f"""
    <form class="space-y-4" method="POST" action="/save-step3" id="step3-form">
      <p class="text-sm text-gray-500 mb-4">Toggle the repositories you want to install and select which branch to use.</p>

      {cards_html}

      <div class="pt-3">
        <button
          type="submit"
          id="install-btn"
          class="py-3 px-4 w-full inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-transparent text-white hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
          style="background-color: {MOOVENT_ACCENT}; --tw-ring-color: {MOOVENT_ACCENT};"
        >
          <svg class="w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"/>
          </svg>
          Install Selected
        </button>
      </div>
    </form>

    <script>
      function toggleRepoCard(checkbox, branchSelectId) {{
        const branchDiv = document.getElementById(branchSelectId);
        if (branchDiv) {{
          branchDiv.style.display = checkbox.checked ? 'block' : 'none';
        }}
        updateInstallButton();
      }}

      function updateInstallButton() {{
        const form = document.getElementById('step3-form');
        const btn = document.getElementById('install-btn');
        const mqttChecked = form.querySelector('input[name="install_mqtt"]')?.checked || false;
        const dashChecked = form.querySelector('input[name="install_dashboard"]')?.checked || false;
        btn.disabled = !mqttChecked && !dashChecked;
      }}

      // Initialize on load
      document.addEventListener('DOMContentLoaded', updateInstallButton);
    </script>
    """
    return _setup_shell(
        "Select repositories",
        "Choose which repositories to install",
        3,
        3,
        content,
        error_text,
    )


def _success_page_html() -> str:
    """Render the success page after saving config (light mode only)."""
    return f"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Ready - Moovent Stack</title>
    <link rel="icon" href="{MOOVENT_LOGO_BASE64}" />
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body class="min-h-screen flex flex-col text-gray-800" style="background-color: {MOOVENT_BACKGROUND};">
    <main class="flex-1 flex items-center justify-center px-4 py-10">
      <div class="w-full max-w-md bg-white border border-gray-200 rounded-xl shadow-sm p-6">
        <div class="mx-auto flex items-center justify-center mb-4">
          <img src="{MOOVENT_LOGO_BASE64}" alt="Moovent" class="h-12" />
        </div>
        <div class="mx-auto w-14 h-14 flex items-center justify-center rounded-full border-2 border-emerald-500 text-emerald-500">
          <svg class="w-7 h-7" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M20 6L9 17l-5-5"/></svg>
        </div>
        <h2 class="mt-4 text-center font-semibold text-lg text-gray-800">You're all set!</h2>
        <p class="mt-2 text-center text-sm text-gray-500">
          Moovent Stack is starting. You can close this tab.
        </p>
        <div class="mt-5 flex justify-center">
          <button type="button" onclick="window.close()" class="py-2.5 px-4 inline-flex justify-center items-center gap-x-2 text-sm font-medium rounded-lg border border-gray-200 bg-white text-gray-800 shadow-sm hover:bg-gray-50 focus:outline-none focus:bg-gray-50">
            Close tab
          </button>
        </div>
      </div>
    </main>

    <footer class="py-6 text-center">
      <p class="text-xs text-gray-400">
        &copy; {_current_year()} Moovent. All rights reserved.
        <span class="mx-1.5">&middot;</span>
        <span class="text-gray-300">v{__version__}</span>
      </p>
    </footer>
    <script>setTimeout(() => window.close(), 800);</script>
  </body>
</html>
""".strip()
