import os
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError


class TestAccessGuard(unittest.TestCase):
    def _mod(self):
        # Import inside test to avoid side effects in module import order.
        from moovent_stack import __main__ as m

        return m

    def test_env_bool_parsing(self):
        m = self._mod()
        self.assertTrue(m._env_bool("true"))
        self.assertTrue(m._env_bool("1"))
        self.assertFalse(m._env_bool("no"))

    def test_cache_validity(self):
        m = self._mod()
        now = time.time()
        self.assertTrue(m._cache_valid({"checked_at": now - 10}, 60))
        self.assertFalse(m._cache_valid({"checked_at": now - 120}, 60))

    def test_safe_install_root_checks_cellar(self):
        m = self._mod()
        self.assertFalse(m._safe_install_root(Path("/")))
        self.assertFalse(m._safe_install_root(Path.home()))
        self.assertTrue(
            m._safe_install_root(
                Path("/opt/homebrew/Cellar/moovent-stack/0.1.0/libexec")
            )
        )

    def test_resolve_runner_path_env(self):
        m = self._mod()
        os.environ[m.RUNNER_ENV_PATH] = "/tmp/run_local_stack.py"
        path = m._resolve_runner_path()
        self.assertEqual(path, Path("/tmp/run_local_stack.py"))
        os.environ.pop(m.RUNNER_ENV_PATH, None)

    def test_validate_runner_path(self):
        m = self._mod()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = root / "run_local_stack.py"
            runner.write_text("# test")
            (root / "mqtt_dashboard_watch").mkdir()
            (root / "dashboard").mkdir()
            ok, error = m._validate_runner_path(runner)
            self.assertTrue(ok)
            self.assertEqual(error, "")

    def test_normalize_infisical_host(self):
        m = self._mod()
        self.assertEqual(
            m._normalize_infisical_host("app.infisical.com"),
            "https://app.infisical.com",
        )
        self.assertEqual(
            m._normalize_infisical_host("https://eu.infisical.com/"),
            "https://eu.infisical.com",
        )

    def test_resolve_infisical_settings_prefers_env(self):
        m = self._mod()
        os.environ[m.INFISICAL_ENV_HOST] = "https://app.infisical.com"
        os.environ[m.INFISICAL_ENV_CLIENT_ID] = "client_id"
        os.environ[m.INFISICAL_ENV_CLIENT_SECRET] = "client_secret"
        host, client_id, client_secret = m._resolve_infisical_settings()
        self.assertEqual(host, "https://app.infisical.com")
        self.assertEqual(client_id, "client_id")
        self.assertEqual(client_secret, "client_secret")
        os.environ.pop(m.INFISICAL_ENV_HOST, None)
        os.environ.pop(m.INFISICAL_ENV_CLIENT_ID, None)
        os.environ.pop(m.INFISICAL_ENV_CLIENT_SECRET, None)

    def test_build_runner_env_injects_infisical_scope(self):
        m = self._mod()
        # Stub to avoid depending on local config file.
        real_resolve_settings = m._resolve_infisical_settings
        real_resolve_scope = m._resolve_infisical_scope
        try:
            m._resolve_infisical_settings = lambda: (
                "https://eu.infisical.com",
                "client_id",
                "client_secret",
            )
            m._resolve_infisical_scope = lambda: (
                "project_id",
                "dev",
                "/",
            )
            env = m._build_runner_env()
            self.assertEqual(env[m.INFISICAL_ENV_ENABLED], "true")
            self.assertEqual(env[m.INFISICAL_ENV_HOST], "https://eu.infisical.com")
            self.assertEqual(env[m.INFISICAL_ENV_CLIENT_ID], "client_id")
            self.assertEqual(env[m.INFISICAL_ENV_CLIENT_SECRET], "client_secret")
            self.assertEqual(env[m.INFISICAL_ENV_PROJECT_ID], "project_id")
            self.assertEqual(env[m.INFISICAL_ENV_ENVIRONMENT], "dev")
            self.assertEqual(env[m.INFISICAL_ENV_SECRET_PATH], "/")
        finally:
            m._resolve_infisical_settings = real_resolve_settings
            m._resolve_infisical_scope = real_resolve_scope

    def test_resolve_github_oauth_settings_prefers_env(self):
        m = self._mod()
        os.environ[m.GITHUB_ENV_CLIENT_ID] = "gh_id"
        os.environ[m.GITHUB_ENV_CLIENT_SECRET] = "gh_secret"
        client_id, client_secret = m._resolve_github_oauth_settings()
        self.assertEqual(client_id, "gh_id")
        self.assertEqual(client_secret, "gh_secret")
        os.environ.pop(m.GITHUB_ENV_CLIENT_ID, None)
        os.environ.pop(m.GITHUB_ENV_CLIENT_SECRET, None)

    def test_write_env_key_updates(self):
        m = self._mod()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / ".env"
            path.write_text("FOO=bar\n# comment\n", encoding="utf-8")
            m._write_env_key(path, "FOO", "baz")
            m._write_env_key(path, "NEW_KEY", "value")
            content = path.read_text(encoding="utf-8")
            self.assertIn("FOO=baz", content)
            self.assertIn("NEW_KEY=value", content)

    def test_setup_noninteractive_flag(self):
        m = self._mod()
        os.environ.pop(m.SETUP_ENV_NONINTERACTIVE, None)
        self.assertFalse(m._setup_noninteractive())
        os.environ[m.SETUP_ENV_NONINTERACTIVE] = "1"
        self.assertTrue(m._setup_noninteractive())

    def test_fetch_infisical_access_requires_project_access(self):
        m = self._mod()
        os.environ[m.INFISICAL_ENV_PROJECT_ID] = m.REQUIRED_INFISICAL_PROJECT_ID

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
        real_urlopen = m.urlopen

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
            m.urlopen = fake_urlopen
            allowed, reason = m._fetch_infisical_access(
                "https://app.infisical.com", "id", "secret"
            )
            self.assertTrue(allowed)
            self.assertEqual(reason, "")
            self.assertEqual(calls["login"], 1)
            self.assertEqual(calls["secrets"], 1)
        finally:
            m.urlopen = real_urlopen
            os.environ.pop(m.INFISICAL_ENV_PROJECT_ID, None)

    def test_fetch_infisical_access_denies_when_project_access_fails(self):
        m = self._mod()
        os.environ[m.INFISICAL_ENV_PROJECT_ID] = m.REQUIRED_INFISICAL_PROJECT_ID

        class _FakeResp:
            def __init__(self, body: str):
                self._body = body.encode("utf-8")

            def read(self) -> bytes:
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        real_urlopen = m.urlopen

        def fake_urlopen(req, timeout=0):  # noqa: ANN001 - matches stdlib signature
            url = getattr(req, "full_url", "")
            if url.endswith("/api/v1/auth/universal-auth/login"):
                return _FakeResp('{"accessToken":"token123"}')
            if "/api/v4/secrets?" in url:
                raise HTTPError(url, 403, "Forbidden", hdrs=None, fp=None)
            raise AssertionError(f"Unexpected url: {url}")

        try:
            m.urlopen = fake_urlopen
            allowed, reason = m._fetch_infisical_access(
                "https://app.infisical.com", "id", "secret"
            )
            self.assertFalse(allowed)
            self.assertEqual(reason, "http_403")
        finally:
            m.urlopen = real_urlopen
            os.environ.pop(m.INFISICAL_ENV_PROJECT_ID, None)

    def test_fetch_infisical_access_rejects_wrong_project_id_if_configured(self):
        m = self._mod()
        os.environ[m.INFISICAL_ENV_PROJECT_ID] = "wrong-project"
        try:
            allowed, reason = m._fetch_infisical_access(
                "https://app.infisical.com", "id", "secret"
            )
            self.assertFalse(allowed)
            self.assertEqual(reason, "project_id_mismatch")
        finally:
            os.environ.pop(m.INFISICAL_ENV_PROJECT_ID, None)


if __name__ == "__main__":
    unittest.main()
