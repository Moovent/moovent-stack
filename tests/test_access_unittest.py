import os
import time
import unittest
from pathlib import Path


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

    def test_parse_access_response_defaults_cleanup_on_deny(self):
        m = self._mod()
        allowed, reason, cleanup = m._parse_access_response({"allowed": False, "reason": "revoked"})
        self.assertFalse(allowed)
        self.assertEqual(reason, "revoked")
        self.assertTrue(cleanup)

    def test_safe_install_root_checks_cellar(self):
        m = self._mod()
        self.assertFalse(m._safe_install_root(Path("/")))
        self.assertFalse(m._safe_install_root(Path.home()))
        self.assertTrue(m._safe_install_root(Path("/opt/homebrew/Cellar/moovent-stack/0.1.0/libexec")))

    def test_remote_defaults(self):
        m = self._mod()
        # Ensure defaults kick in when env vars not set.
        os.environ.pop(m.REMOTE_ENV_URL, None)
        os.environ.pop(m.REMOTE_ENV_BACKEND_URL, None)
        self.assertTrue(m._remote_url().startswith("https://"))
        self.assertTrue(m._remote_backend_url().startswith("https://"))


if __name__ == "__main__":
    unittest.main()

