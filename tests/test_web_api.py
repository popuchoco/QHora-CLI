import json
import unittest
from io import BytesIO
from unittest.mock import patch
import urllib.error

from qrouter_cli.web_api import QuRouterWebAPI, RouterAPIError, _project_section, router_web_status


class WebAPITests(unittest.TestCase):
    def test_login_encodes_password_and_never_forces_existing_session(self):
        api = QuRouterWebAPI("https://router/miro/api", "monitor", "sëcret")
        calls = []

        def fake_request(path, **kwargs):
            calls.append((path, kwargs))
            return {"result": {"access_token": "private-token"}}

        with patch.object(api, "_request", side_effect=fake_request):
            api.login()
        self.assertEqual(api.token, "private-token")
        self.assertEqual(calls[0][0], "/v1/login")
        payload = calls[0][1]["payload"]
        self.assertEqual(payload["force"], False)
        self.assertEqual(payload["remember_me"], False)
        self.assertNotEqual(payload["password"], "sëcret")

    def test_existing_session_is_not_displaced(self):
        api = QuRouterWebAPI("https://router/miro/api", "monitor", "secret")
        with patch.object(api, "_request", return_value={"result": {"had_session": True}}):
            with self.assertRaisesRegex(RouterAPIError, "active management session"):
                api.login()
        self.assertIsNone(api.token)

    def test_plain_http_requires_explicit_private_lan_opt_in(self):
        with self.assertRaisesRegex(RouterAPIError, "HTTPS is required"):
            QuRouterWebAPI("http://router/miro/api", "monitor", "secret")
        api = QuRouterWebAPI("http://router/miro/api", "monitor", "secret", allow_insecure_http=True)
        self.assertEqual(api.transport, "http_unencrypted")

    def test_web_status_reads_fixed_endpoints_and_reports_partial_errors(self):
        class FakeAPI:
            transport = "https"
            def __init__(self): self.reads = []
            def login(self): self.logged_in = True
            def get(self, section):
                self.reads.append(section)
                if section == "overview": return {"firmware_version": "test", "cpu_load": 1.5}
                raise RouterAPIError("QuRouter API error -2: backend unavailable", error_code=-2)
            def logout(self): self.logged_out = True

        fake = FakeAPI()
        with patch("qrouter_cli.web_api.QuRouterWebAPI.from_environment", return_value=fake):
            result = router_web_status()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sections"]["overview"]["data"]["firmware_version"], "test")
        self.assertEqual(result["sections"]["ports"]["status"], "unavailable")
        self.assertEqual(fake.reads, ["overview", "ports", "wan"])
        self.assertTrue(fake.logged_out)

    def test_base_url_rejects_embedded_credentials(self):
        with self.assertRaises(RouterAPIError):
            QuRouterWebAPI("http://admin:secret@router/api", "admin", "secret")

    def test_overview_projection_omits_wan_identity_and_unknown_fields(self):
        result = _project_section("overview", {"firmware_version": "test", "wan_ip_0": "203.0.113.10", "site": "private", "new_secret": "hidden"})
        self.assertEqual(result, {"firmware_version": "test"})

    def test_ports_projection_keeps_status_but_drops_unrecognized_fields(self):
        result = _project_section("ports", {"lan": [{"portName": "LAN1", "status": "up", "macAddress": "hidden"}], "unexpected": [{"secret": "hidden"}]})
        self.assertEqual(result, {"lan": [{"portName": "LAN1", "status": "up"}]})

    def test_http_error_extracts_safe_firmware_error_code(self):
        api = QuRouterWebAPI("https://router/miro/api", "monitor", "secret")
        body = json.dumps({"error_code": -2, "error_message": "QSH backend unavailable"}).encode()
        response = urllib.error.HTTPError("https://router/api", 519, "firmware error", {}, BytesIO(body))
        with patch.object(api._opener, "open", side_effect=response):
            with self.assertRaises(RouterAPIError) as raised:
                api._request("/v2/network/ports_status")
        self.assertEqual(raised.exception.error_code, -2)
        self.assertIn("HTTP 519", str(raised.exception))
        self.assertIn("API error -2", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
