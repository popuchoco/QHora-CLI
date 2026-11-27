"""Minimal stdio MCP server exposing fixed read-only QuRouter and Kuma tools."""

import json
import sys

from .collectors import CollectorError, integrated_router_status, kuma_monitor_status, kuma_status, router_read, router_status
from .web_api import RouterAPIError, router_web_status
from .logging_utils import emit_log

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


def _error(request_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _dispatch(message: dict):
    if not isinstance(message, dict):
        return _error(None, -32600, "Invalid Request")
    request_id = message.get("id")
    has_id = "id" in message
    method = message.get("method")
    if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return _error(request_id if has_id else None, -32600, "Invalid Request")
    if method.startswith("notifications/"):
        return _error(request_id, -32600, "Notifications must not include an id") if has_id else None
    if not has_id:
        return None
    params = message.get("params", {})
    if not isinstance(params, dict):
        return _error(request_id, -32602, "Invalid params")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "qrouter-cli", "version": "0.1.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments", {})
        if not isinstance(args, dict):
            return _error(request_id, -32602, "Invalid params")
        try:
            if name == "qrouter_router_status" and not args: result = router_status()
            elif name == "qrouter_router_read" and set(args) == {"section"}: result = router_read(args["section"])
            elif name == "qrouter_web_status" and not args: result = router_web_status()
            elif name == "qrouter_integrated_status" and not args: result = integrated_router_status()
            elif name == "qrouter_kuma_status" and not args: result = kuma_status()
            elif name == "qrouter_kuma_monitor" and set(args) == {"monitor_name"}: result = kuma_monitor_status(args["monitor_name"])
            else: raise CollectorError("Unknown tool or invalid arguments")
            return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}], "isError": False}}
        except (CollectorError, RouterAPIError) as exc:
            emit_log("mcp_tool_failed", "WARNING", component="mcp", error_type=type(exc).__name__)
            return {"jsonrpc": "2.0", "id": request_id, "result": {"content": [{"type": "text", "text": str(exc)}], "isError": True}}
    return _error(request_id, -32601, "Method not found")


def handle(message) -> None:
    if isinstance(message, list):
        if not message:
            reply(_error(None, -32600, "Invalid Request"))
            return
        responses = [response for item in message if (response := _dispatch(item)) is not None]
        if responses:
            reply(responses)
        return
    response = _dispatch(message)
    if response is not None:
        reply(response)


def main() -> None:
    for line in sys.stdin:
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
            continue
        handle(message)


if __name__ == "__main__":
    main()
