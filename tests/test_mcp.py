import unittest
from unittest.mock import patch

from qrouter_cli import mcp_server


class MCPTests(unittest.TestCase):
    def test_tools_list_exposes_web_kuma_and_combined_status(self):
        replies = []
        with patch.object(mcp_server, "reply", replies.append):
            mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        names = {tool["name"] for tool in replies[0]["result"]["tools"]}
        self.assertIn("qrouter_web_status", names)
        self.assertIn("qrouter_integrated_status", names)
        self.assertIn("qrouter_kuma_status", names)
        self.assertIn("qrouter_kuma_monitor", names)

    def test_combined_status_tool_dispatches(self):
        replies = []
        expected = {"status": "partial", "source": "qhora_web_api_and_uptime_kuma"}
        with patch.object(mcp_server, "reply", replies.append), patch.object(mcp_server, "integrated_router_status", return_value=expected):
            mcp_server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "qrouter_integrated_status", "arguments": {}}})
        self.assertFalse(replies[0]["result"]["isError"])
        self.assertIn('"status": "partial"', replies[0]["result"]["content"][0]["text"])

    def test_unknown_or_extra_arguments_are_rejected(self):
        replies = []
        with patch.object(mcp_server, "reply", replies.append):
            mcp_server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "qrouter_web_status", "arguments": {"url": "http://127.0.0.1"}}})
        self.assertTrue(replies[0]["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
