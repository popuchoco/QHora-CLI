import json
import os
import unittest
from unittest.mock import patch

from qrouter_cli.logging_utils import emit_log


class LoggingTests(unittest.TestCase):
    def test_logs_only_allowlisted_metadata(self):
        with patch.dict(os.environ, {"QROUTER_LOG_LEVEL": "INFO"}), patch("sys.stderr") as stderr:
            emit_log("request_failed", "WARNING", component="web", error_type="RouterAPIError", password="secret", token="bearer-secret", message="https://user:pass@host")
        record = json.loads(stderr.write.call_args.args[0])
        self.assertEqual(record["component"], "web")
        self.assertNotIn("password", record)
        self.assertNotIn("token", record)
        self.assertNotIn("message", record)

    def test_logging_is_off_by_default(self):
        with patch.dict(os.environ, {}, clear=True), patch("sys.stderr") as stderr:
            emit_log("test", component="cli")
        stderr.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
