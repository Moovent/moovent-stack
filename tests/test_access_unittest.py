import os
import tempfile
import time
import unittest
import warnings
from pathlib import Path
from urllib.error import HTTPError

from moovent_stack import access, config, github, infisical, runner, workspace


class TestAccessGuard(unittest.TestCase):
    def test_env_bool_parsing(self):
        self.assertTrue(config._env_bool("true"))
        self.assertTrue(config._env_bool("1"))
        self.assertFalse(config._env_bool("no"))

    def test_cache_validity(self):
        now = time.time()
        self.assertTrue(access._cache_valid({"checked_at": now - 10}, 60))
        self.assertFalse(access._cache_valid({"checked_at": now - 120}, 60))

    def test_safe_install_root_checks_cellar(self):
        self.assertFalse(workspace._safe_install_root(Path("/")))
        self.assertFalse(workspace._safe_install_root(Path.home()))
        self.assertTrue(
            workspace._safe_install_root(
                Path("/opt/homebrew/Cellar/moovent-stack/0.1.0/libexec")
            )
        )

    def test_resolve_runner_path_env(self):
        os.environ[config.RUNNER_ENV_PATH] = "/tmp/run_local_stack.py"
        path = workspace._resolve_runner_path()
        self.assertEqual(path, Path("/tmp/run_local_stack.py"))
        os.environ.pop(config.RUNNER_ENV_PATH, None)

    def test_validate_runner_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = root / "run_local_stack.py"
            runner.write_text("# test")
            (root / "mqtt_dashboard_watch").mkdir()
            (root / "dashboard").mkdir()
            ok, error = workspace._validate_runner_path(runner)
            self.assertTrue(ok)
            self.assertEqual(error, "")

    def test_validate_runner_path_allows_missing_dashboard_when_unselected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = root / "run_local_stack.py"
            runner.write_text("# test")
            (root / "mqtt_dashboard_watch").mkdir()
            ok, error = workspace._validate_runner_path(
                runner, config_override={"install_dashboard": False}
            )
            self.assertTrue(ok)
            self.assertEqual(error, "")

    def test_validate_runner_path_allows_missing_mqtt_when_unselected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = root / "run_local_stack.py"
            runner.write_text("# test")
            (root / "dashboard").mkdir()
            ok, error = workspace._validate_runner_path(
                runner, config_override={"install_mqtt": False, "install_dashboard": True}
            )
            self.assertTrue(ok)
            self.assertEqual(error, "")

    def test_validate_runner_path_requires_selection_when_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = root / "run_local_stack.py"
            runner.write_text("# test")
            ok, error = workspace._validate_runner_path(
                runner,
                config_override={"install_mqtt": False, "install_dashboard": False},
            )
            self.assertFalse(ok)
            self.assertEqual(error, "No repositories selected for installation.")

    def test_normalize_infisical_host(self):
        self.assertEqual(
            infisical._normalize_infisical_host("app.infisical.com"),
            "https://app.infisical.com",
        )
        self.assertEqual(
            infisical._normalize_infisical_host("https://eu.infisical.com/"),
            "https://eu.infisical.com",
        )

    def test_resolve_infisical_settings_prefers_env(self):
        os.environ[config.INFISICAL_ENV_HOST] = "https://app.infisical.com"
        os.environ[config.INFISICAL_ENV_CLIENT_ID] = "client_id"
        os.environ[config.INFISICAL_ENV_CLIENT_SECRET] = "client_secret"
        host, client_id, client_secret = infisical._resolve_infisical_settings()
        self.assertEqual(host, "https://app.infisical.com")
        self.assertEqual(client_id, "client_id")
        self.assertEqual(client_secret, "client_secret")
        os.environ.pop(config.INFISICAL_ENV_HOST, None)
        os.environ.pop(config.INFISICAL_ENV_CLIENT_ID, None)
        os.environ.pop(config.INFISICAL_ENV_CLIENT_SECRET, None)

    def test_build_runner_env_injects_infisical_scope(self):
        # Stub to avoid depending on local config file.
        real_resolve_settings = runner._resolve_infisical_settings
        real_resolve_scope = runner._resolve_infisical_scope
        try:
            runner._resolve_infisical_settings = lambda: (
                "https://eu.infisical.com",
                "client_id",
                "client_secret",
            )
            runner._resolve_infisical_scope = lambda: (
                "project_id",
                "dev",
                "/",
            )
            env = runner._build_runner_env()
            self.assertEqual(env[config.INFISICAL_ENV_ENABLED], "true")
            self.assertEqual(env[config.INFISICAL_ENV_HOST], "https://eu.infisical.com")
            self.assertEqual(env[config.INFISICAL_ENV_CLIENT_ID], "client_id")
            self.assertEqual(env[config.INFISICAL_ENV_CLIENT_SECRET], "client_secret")
            self.assertEqual(env[config.INFISICAL_ENV_PROJECT_ID], "project_id")
            self.assertEqual(env[config.INFISICAL_ENV_ENVIRONMENT], "dev")
            self.assertEqual(env[config.INFISICAL_ENV_SECRET_PATH], "/")
        finally:
            runner._resolve_infisical_settings = real_resolve_settings
            runner._resolve_infisical_scope = real_resolve_scope

    def test_build_runner_env_exports_all_when_enabled(self):
        """
        When INFISICAL_EXPORT_ALL=true, runner should export all secrets (not just defaults).
        """
        real_resolve_settings = runner._resolve_infisical_settings
        real_resolve_scope = runner._resolve_infisical_scope
        real_fetch_all = runner._fetch_infisical_env_all
        real_fetch_subset = runner._fetch_infisical_env_exports
        try:
            os.environ[config.INFISICAL_EXPORT_ALL_ENV] = "true"
            runner._resolve_infisical_settings = lambda: (
                "https://eu.infisical.com",
                "client_id",
                "client_secret",
            )
            runner._resolve_infisical_scope = lambda: (
                "project_id",
                "dev",
                "/",
            )
            runner._fetch_infisical_env_all = lambda *_args, **_kwargs: {
                "BROKER": "broker",
                "OPENAI_API_KEY": "sk-test",
            }
            runner._fetch_infisical_env_exports = lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("_fetch_infisical_env_exports should not be called when export-all is enabled")
            )

            env = runner._build_runner_env()
            self.assertEqual(env.get("OPENAI_API_KEY"), "sk-test")
        finally:
            os.environ.pop(config.INFISICAL_EXPORT_ALL_ENV, None)
            runner._resolve_infisical_settings = real_resolve_settings
            runner._resolve_infisical_scope = real_resolve_scope
            runner._fetch_infisical_env_all = real_fetch_all
            runner._fetch_infisical_env_exports = real_fetch_subset

    def test_resolve_github_oauth_settings_prefers_env(self):
        os.environ[config.GITHUB_ENV_CLIENT_ID] = "gh_id"
        os.environ[config.GITHUB_ENV_CLIENT_SECRET] = "gh_secret"
        client_id, client_secret = github._resolve_github_oauth_settings()
        self.assertEqual(client_id, "gh_id")
        self.assertEqual(client_secret, "gh_secret")
        os.environ.pop(config.GITHUB_ENV_CLIENT_ID, None)
        os.environ.pop(config.GITHUB_ENV_CLIENT_SECRET, None)

    def test_write_env_key_updates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / ".env"
            path.write_text("FOO=bar\n# comment\n", encoding="utf-8")
            workspace._write_env_key(path, "FOO", "baz")
            workspace._write_env_key(path, "NEW_KEY", "value")
            content = path.read_text(encoding="utf-8")
            self.assertIn("FOO=baz", content)
            self.assertIn("NEW_KEY=value", content)

    def test_setup_noninteractive_flag(self):
        os.environ.pop(config.SETUP_ENV_NONINTERACTIVE, None)
        self.assertFalse(config._setup_noninteractive())
        os.environ[config.SETUP_ENV_NONINTERACTIVE] = "1"
        self.assertTrue(config._setup_noninteractive())

    def test_fetch_infisical_access_requires_project_access(self):
        os.environ[config.INFISICAL_ENV_PROJECT_ID] = (
            config.REQUIRED_INFISICAL_PROJECT_ID
        )

        class _FakeResp:
            def __init__(self, body: str):
                self._body = body.encode("utf-8")

            def read(self) -> bytes:
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        calls = {"login": 0, "secrets": 0}
        real_urlopen = infisical.urlopen

        def fake_urlopen(req, timeout=0):  # noqa: ANN001 - matches stdlib signature
            url = getattr(req, "full_url", "")
            if url.endswith("/api/v1/auth/universal-auth/login"):
                calls["login"] += 1
                return _FakeResp('{"accessToken":"token123"}')
            if "/api/v4/secrets?" in url:
                calls["secrets"] += 1
                return _FakeResp('{"secrets":[],"imports":[]}')
            raise AssertionError(f"Unexpected url: {url}")

        try:
            infisical.urlopen = fake_urlopen
            allowed, reason = infisical._fetch_infisical_access(
                "https://app.infisical.com", "id", "secret"
            )
            self.assertTrue(allowed)
            self.assertEqual(reason, "")
            self.assertEqual(calls["login"], 1)
            self.assertEqual(calls["secrets"], 1)
        finally:
            infisical.urlopen = real_urlopen
            os.environ.pop(config.INFISICAL_ENV_PROJECT_ID, None)

    def test_fetch_infisical_access_denies_when_project_access_fails(self):
        os.environ[config.INFISICAL_ENV_PROJECT_ID] = (
            config.REQUIRED_INFISICAL_PROJECT_ID
        )

        class _FakeResp:
            def __init__(self, body: str):
                self._body = body.encode("utf-8")

            def read(self) -> bytes:
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        real_urlopen = infisical.urlopen

        def fake_urlopen(req, timeout=0):  # noqa: ANN001 - matches stdlib signature
            url = getattr(req, "full_url", "")
            if url.endswith("/api/v1/auth/universal-auth/login"):
                return _FakeResp('{"accessToken":"token123"}')
            if "/api/v4/secrets?" in url:
                raise HTTPError(url, 403, "Forbidden", hdrs=None, fp=None)
            raise AssertionError(f"Unexpected url: {url}")

        try:
            infisical.urlopen = fake_urlopen
            # Suppress ResourceWarning from HTTPError cleanup on some Python versions.
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", category=ResourceWarning)
                allowed, reason = infisical._fetch_infisical_access(
                    "https://app.infisical.com", "id", "secret"
                )
            self.assertFalse(allowed)
            self.assertEqual(reason, "http_403")
        finally:
            infisical.urlopen = real_urlopen
            os.environ.pop(config.INFISICAL_ENV_PROJECT_ID, None)

    def test_fetch_infisical_access_rejects_wrong_project_id_if_configured(self):
        os.environ[config.INFISICAL_ENV_PROJECT_ID] = "wrong-project"
        try:
            allowed, reason = infisical._fetch_infisical_access(
                "https://app.infisical.com", "id", "secret"
            )
            self.assertFalse(allowed)
            self.assertEqual(reason, "project_id_mismatch")
        finally:
            os.environ.pop(config.INFISICAL_ENV_PROJECT_ID, None)


if __name__ == "__main__":
    unittest.main()
