import os
import tempfile
import unittest

from scripts.destiny_env import load_env


class LoadEnvTests(unittest.TestCase):
    def test_load_env_handles_crlf_comments_quotes(self):
        raw = b'# c\r\nHA_URL="http://x:8123"\r\n\r\nHA_TOKEN=abc\r\nEMPTY=\r\n'
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, ".env")
            with open(path, "wb") as f:
                f.write(raw)
            self.assertEqual(
                load_env(path),
                {"HA_URL": "http://x:8123", "HA_TOKEN": "abc", "EMPTY": ""},
            )

    def test_load_env_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_env(os.path.join(d, "nope.env")), {})


if __name__ == "__main__":
    unittest.main()
