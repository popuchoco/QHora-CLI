import os
import unittest
from unittest.mock import patch

from qrouter_cli import collectors


class CollectorParsingTests(unittest.TestCase):
    def test_free_parser_handles_commas_and_case(self):
        self.assertEqual(collectors._parse_free("Mem: 1,024 512 256 10 20 30"), {"total": 1024, "used": 512, "free": 256})
        self.assertIsNone(collectors._parse_free("memory unavailable"))

    def test_wifi_parser_extracts_bounded_useful_metadata(self):
        output = """phy#0
\tInterface wlan0
\t\tssid Home Network
\t\ttxpower 17.5 dBm
\t\tchannel 36 (5180 MHz), width: 80 MHz, center1: 5210 MHz
"""
        self.assertEqual(collectors._parse_wifi(output), [{"interface": "wlan0", "ssid": "Home Network", "txpower_dbm": 17.5, "channel": 36, "frequency_mhz": 5180, "width": "80 MHz"}])

    def test_wifi_parser_handles_multiple_radios_and_variant_spacing(self):
        output = """phy#0
Interface wlan0
\tssid Guest
\tchannel 1 (2412 MHz), width: 20 MHz, center1: 2412 MHz
phy#1
Interface wlan1
\tchannel 149 (5745 MHz), width: 80MHz, center1: 5775 MHz
\ttxpower 20.00 dBm
"""
        got = collectors._parse_wifi(output)
        self.assertEqual([radio["interface"] for radio in got], ["wlan0", "wlan1"])
        self.assertEqual(got[0]["ssid"], "Guest")
        self.assertEqual(got[1]["channel"], 149)
        self.assertEqual(got[1]["txpower_dbm"], 20.0)

    def test_neighbors_allow_missing_attributes_and_states(self):
        got = collectors._parse_neighbors("192.0.2.1 dev br0 lladdr aa:bb:cc:dd:ee:ff REACHABLE\n192.0.2.2 INCOMPLETE\n")
        self.assertEqual(got[0], {"address": "192.0.2.1", "interface": "br0", "state": "REACHABLE", "mac": "aa:bb:cc:dd:ee:ff"})
        self.assertEqual(got[1]["state"], "INCOMPLETE")
        self.assertIsNone(got[1]["mac"])

    def test_neighbors_preserve_unknown_state_for_diagnostics(self):
        got = collectors._parse_neighbors("192.0.2.3 dev br0 VERIFYING")
        self.assertEqual(got[0]["state"], "VERIFYING")

    def test_ssh_host_validation_accepts_ip_and_dns_only(self):
        for host in ("192.168.1.1", "2001:db8::1", "router.example.net"):
            self.assertTrue(collectors._valid_ssh_host(host), host)
        for host in ("192.168.1.999", "router..local", "-bad.example", "router.example-", "router;whoami", "host name"):
            self.assertFalse(collectors._valid_ssh_host(host), host)

    def test_raw_parse_diagnostics_require_opt_in_and_are_bounded(self):
        lines = "\n".join("x" * 300 for _ in range(30))
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(collectors._parse_diagnostics("wifi", lines), {})
        with patch.dict(os.environ, {"QROUTER_INCLUDE_RAW_ON_PARSE_ERROR": "1"}):
            got = collectors._parse_diagnostics("wifi", lines)["wifi"]
        self.assertEqual(len(got), 10)
        self.assertTrue(all(len(line) == 200 for line in got))


if __name__ == "__main__":
    unittest.main()
