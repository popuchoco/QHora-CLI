import os
import unittest
from unittest.mock import patch

from qrouter_cli import collectors


PAGE = {
    "config": {"title": "Home"},
    "publicGroupList": [
        {"name": "Network", "monitorList": [{"id": 7, "name": "QuRouter Web", "type": "http"}, {"id": 8, "name": "Third-party API", "type": "http"}]}
    ],
}
HEARTBEAT = {"heartbeatList": {
    "7": [{"status": 1, "ping": 22.4, "time": "2026-11-27 02:00:00.000"}],
    "8": [{"status": 0, "ping": None, "time": "2026-11-27 02:00:00.000"}],
}}


class KumaTests(unittest.TestCase):
    def setUp(self):
        collectors._KUMA_CACHE = None
        collectors._KUMA_CACHE_AT = 0
        self.env = patch.dict(os.environ, {"KUMA_BASE_URL": "http://kuma:3001", "KUMA_STATUS_SLUG": "home-network", "KUMA_CACHE_TTL": "15"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.reset_cache)

    @staticmethod
    def reset_cache():
        collectors._KUMA_CACHE = None
        collectors._KUMA_CACHE_AT = 0

    def test_status_normalizes_monitors_including_third_party_api(self):
        with patch.object(collectors, "_http_json", side_effect=[PAGE, HEARTBEAT]):
            result = collectors.kuma_status(force_refresh=True)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["monitors"][0]["status"], "up")
        self.assertEqual(result["monitors"][0]["ping_ms"], 22.4)
        self.assertEqual(result["monitors"][1]["name"], "Third-party API")
        self.assertEqual(result["monitors"][1]["status"], "down")

    def test_monitor_lookup_uses_exact_name_and_cached_snapshot(self):
        with patch.object(collectors, "_http_json", side_effect=[PAGE, HEARTBEAT]) as fetch:
            result = collectors.kuma_monitor_status("QuRouter Web")
            self.assertEqual(collectors.kuma_monitor_status("QuRouter Web")["matches"][0]["status"], "up")
        self.assertEqual(result["matches"][0]["name"], "QuRouter Web")
        self.assertEqual(fetch.call_count, 2)

    def test_refresh_failure_returns_stale_last_known_good(self):
        with patch.object(collectors, "_http_json", side_effect=[PAGE, HEARTBEAT]):
            first = collectors.kuma_status(force_refresh=True)
        with patch.object(collectors, "_http_json", side_effect=collectors.CollectorError("offline")):
            stale = collectors.kuma_status(force_refresh=True)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(len(stale["monitors"]), 2)

    def test_integrated_status_combines_web_api_and_kuma_monitor(self):
        web = {"source": "qrouter_web_api", "status": "partial"}
        kuma = {"source": "uptime_kuma_status_page", "status": "ok", "matches": [{"name": "QuRouter Web", "status": "up"}]}
        with patch.object(collectors, "router_web_status", return_value=web), patch.object(collectors, "kuma_monitor_status", return_value=kuma):
            result = collectors.integrated_router_status()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["qurouter_web_api"], web)
        self.assertEqual(result["uptime_kuma_qurouter_web"], kuma)


if __name__ == "__main__":
    unittest.main()
