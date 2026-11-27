"""Minimal stdio MCP server exposing fixed read-only QuRouter and Kuma tools."""

import json
import sys

from .collectors import CollectorError, integrated_router_status, kuma_monitor_status, kuma_status, router_read, router_status
from .web_api import RouterAPIError, router_web_status

PROTOCOL_VERSION = "2024-11-05"
TOOLS = [
    {"name": "qrouter_router_status", "description": "Read QHora system, interfaces, Wi-Fi and resource summary over fixed read-only SSH commands.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "qrouter_router_read", "description": "Read one allowlisted QHora section: interfaces, addresses, routes, neighbors, wifi, listeners, or filesystems.", "inputSchema": {"type": "object", "properties": {"section": {"type": "string", "enum": ["interfaces", "addresses", "routes", "neighbors", "wifi", "listeners", "filesystems"]}}, "required": ["section"], "additionalProperties": False}},
    {"name": "qrouter_web_status", "description": "Read QuRouter overview, port and WAN status using the QHora Web API; never changes router configuration or forces an existing session.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "qrouter_integrated_status", "description": "Cross-check direct QHora Web API data with the QuRouter Web availability monitor from Uptime Kuma.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "qrouter_kuma_status", "description": "Read the configured published Uptime Kuma status page as normalized monitor status, including third-party API monitors.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "qrouter_kuma_monitor", "description": "Read one monitor by exact name from the configured Uptime Kuma status page.", "inputSchema": {"type": "object", "properties": {"monitor_name": {"type": "string", "minLength": 1, "maxLength": 120}}, "required": ["monitor_name"], "additionalProperties": False}},
]


def reply(message: dict) -> None:
    sys.stdout.write(json.dumps(message, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def handle(message: dict) -> None:
    method, request_id = message.get("method"), message.get("id")
    params = message.get("params") or {}
    if method == "notifications/initialized":
        return
    if method == "initialize":
        reply({"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "qrouter-cli", "version": "0.1.0"}}})
    elif method == "ping":
        reply({"jsonrpc": "2.0", "id": request_id, "result": {}})
    elif method == "tools/list":
        reply({"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}})
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        try:
            if name == "qrouter_router_status" and not args: result = router_status()
            elif name == "qrouter_router_read" and set(args) == {"section"}: result = router_read(args["section"])
            elif name == "qrouter_web_status" and not args: result = router_web_status()
            elif name == "qrouter_integrated_status" and not args: result = integrated_router_status()
            elif name == "qrouter_kuma_status" and not args: result = kuma_status()
            elif name == "qrouter_kuma_monitor" and set(args) == {"monitor_name"}: result = kuma_monitor_status(args["monitor_name"])
            else: raise CollectorError("Unknown tool")
            reply({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "isError": False}})
        except (CollectorError, RouterAPIError) as exc:
            reply({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": str(exc)}], "isError": True}})
    elif request_id is not None:
        reply({"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}})


def main() -> None:
    for line in sys.stdin:
        try:
            handle(json.loads(line))
        except (json.JSONDecodeError, TypeError):
            continue


if __name__ == "__main__":
    main()
