"""Minimal stdio MCP server exposing fixed read-only QuRouter and Kuma tools."""

import json
import sys

from .collectors import CollectorError, kuma_status, router_read, router_status

PROTOCOL_VERSION = "2024-11-05"
TOOLS = [
    {"name": "qrouter_router_status", "description": "Read QHora system, interfaces, Wi-Fi and resource summary over fixed read-only SSH commands.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "qrouter_router_read", "description": "Read one allowlisted QHora section: interfaces, addresses, routes, neighbors, wifi, listeners, or filesystems.", "inputSchema": {"type": "object", "properties": {"section": {"type": "string", "enum": ["interfaces", "addresses", "routes", "neighbors", "wifi", "listeners", "filesystems"]}}, "required": ["section"], "additionalProperties": False}},
    {"name": "qrouter_kuma_status", "description": "Read the configured published Uptime Kuma status page and heartbeat snapshot.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
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
            elif name == "qrouter_kuma_status" and not args: result = kuma_status()
            else: raise CollectorError("Unknown tool")
            reply({"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "isError": False}})
        except CollectorError as exc:
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
