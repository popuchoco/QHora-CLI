"""Read-only QuRouter Web API client for QHora routers."""

from __future__ import annotations

import base64
import json
import os
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


MAX_RESPONSE_BYTES = 1024 * 1024
READ_ENDPOINTS = {
    "overview": "/v1/debugmode/information",
    "ports": "/v2/network/ports_status",
    "wan": "/v2/network/wan/status",
}
OVERVIEW_FIELDS = (
    "firmware_version", "firmware_build_time", "operation_mode", "cpu_load", "cpu_temp",
    "mem_used", "mem_total", "uptime", "conntrack_count", "dpi_enable", "quwan_enable",
)
PORT_FIELDS = ("portName", "status", "linkRate", "throughputTx", "throughputRx", "occupiedIfNames")
WAN_FIELDS = ("ifname", "linkStatus", "ip4Type", "ip4Address", "ip4Gateway", "ip4DnsServers", "ip6Type", "ip6Address")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, new_url):
        return None


class RouterAPIError(RuntimeError):
    def __init__(self, message: str, *, error_code: int | None = None):
        super().__init__(message)
        self.error_code = error_code


def _load_password() -> str:
    filename = os.environ.get("QROUTER_WEB_PASSWORD_FILE", "")
    if filename:
        try:
            value = Path(filename).read_text(encoding="utf-8").rstrip("\r\n")
            if value:
                return value
            raise RouterAPIError("QROUTER_WEB_PASSWORD_FILE is empty")
        except OSError as exc:
            raise RouterAPIError("Could not read QROUTER_WEB_PASSWORD_FILE") from exc
    value = os.environ.get("QROUTER_WEB_PASSWORD")
    if value:
        return value.rstrip("\r\n")
    raise RouterAPIError("Set QROUTER_WEB_PASSWORD or QROUTER_WEB_PASSWORD_FILE")


class QuRouterWebAPI:
    """A per-call API session; credentials and bearer token are never returned."""

    def __init__(self, base_url: str, username: str, password: str, timeout: float = 8.0,
                 allow_insecure_http: bool = False, ca_file: str = ""):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise RouterAPIError("QROUTER_WEB_BASE_URL must be an http(s) URL without embedded credentials")
        if parsed.query or parsed.fragment:
            raise RouterAPIError("QROUTER_WEB_BASE_URL cannot include a query or fragment")
        if parsed.scheme == "http" and not allow_insecure_http:
            raise RouterAPIError("HTTPS is required; set QROUTER_WEB_ALLOW_INSECURE_HTTP=1 only on a trusted private LAN")
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        self.token: str | None = None
        self.transport = "https" if parsed.scheme == "https" else "http_unencrypted"
        try:
            tls_context = ssl.create_default_context(cafile=ca_file or None)
        except (OSError, ssl.SSLError) as exc:
            raise RouterAPIError("Could not load QROUTER_WEB_CA_FILE") from exc
        self._opener = urllib.request.build_opener(_NoRedirect(), urllib.request.HTTPSHandler(context=tls_context))

    @classmethod
    def from_environment(cls) -> "QuRouterWebAPI":
        base = os.environ.get("QROUTER_WEB_BASE_URL", "").strip()
        if not base:
            raise RouterAPIError("Set QROUTER_WEB_BASE_URL explicitly; no HTTP default is used")
        username = os.environ.get("QROUTER_WEB_USERNAME", "admin")
        allow_http = os.environ.get("QROUTER_WEB_ALLOW_INSECURE_HTTP", "").lower() in ("1", "true", "yes")
        return cls(base, username, _load_password(), allow_insecure_http=allow_http,
                   ca_file=os.environ.get("QROUTER_WEB_CA_FILE", ""))

    def _request(self, path: str, *, method: str = "GET", payload: dict | None = None, authenticated: bool = True) -> dict[str, Any]:
        if not path.startswith("/") or ".." in path.split("/"):
            raise RouterAPIError("Invalid fixed router API path")
        headers = {"Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if authenticated and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise RouterAPIError("QuRouter response exceeded 1 MiB")
        except urllib.error.HTTPError as exc:
            # Preserve a numeric firmware error code, but never echo arbitrary response bodies.
            error_code = None
            detail = ""
            try:
                raw_error = exc.read(MAX_RESPONSE_BYTES + 1)
                if len(raw_error) <= MAX_RESPONSE_BYTES:
                    body = json.loads(raw_error)
                    if isinstance(body, dict):
                        code = body.get("error_code")
                        error_code = code if isinstance(code, int) else None
                        message = str(body.get("error_message") or "")[:240]
                        message = re.sub(r"(?i)(password|token|authorization|secret)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", message)
                        detail = f" API error {error_code}: {message}" if error_code is not None and message else f" API error {error_code}" if error_code is not None else ""
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                pass
            exc.close()
            raise RouterAPIError(f"QuRouter HTTP request failed (HTTP {exc.code}){detail}", error_code=error_code) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RouterAPIError("QuRouter HTTP request failed or timed out") from exc
        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RouterAPIError("QuRouter returned invalid JSON") from exc
        if not isinstance(result, dict):
            raise RouterAPIError("QuRouter returned an unexpected response")
        code = result.get("error_code", 0)
        if code not in (0, None):
            message = str(result.get("error_message") or "API request rejected")[:240]
            message = re.sub(r"(?i)(password|token|authorization|secret)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", message)
            raise RouterAPIError(f"QuRouter API error {code}: {message}", error_code=code if isinstance(code, int) else None)
        return result

    def login(self) -> None:
        encoded = base64.b64encode(self.password.encode("utf-8")).decode("ascii")
        response = self._request(
            "/v1/login",
            method="POST",
            payload={"username": self.username, "password": encoded, "force": False,
                     "remember_me": False, "qid_login": False},
            authenticated=False,
        )
        result = response.get("result") or {}
        token = result.get("access_token") if isinstance(result, dict) else None
        if not token:
            if isinstance(result, dict) and result.get("had_session"):
                raise RouterAPIError("QuRouter has an active management session; login was not forced", error_code=-3)
            raise RouterAPIError("QuRouter login did not return an access token")
        self.token = str(token)

    def get(self, section: str) -> Any:
        endpoint = READ_ENDPOINTS.get(section)
        if endpoint is None:
            raise RouterAPIError("Unsupported read-only QuRouter section")
        if not self.token:
            raise RouterAPIError("QuRouter API session is not authenticated")
        response = self._request(endpoint)
        result = response.get("result")
        if not isinstance(result, (dict, list)):
            raise RouterAPIError("QuRouter returned an unexpected result shape")
        return result

    def logout(self) -> None:
        if not self.token:
            return
        try:
            self._request("/v1/logout", method="POST", payload={})
        finally:
            self.token = None


def router_web_status() -> dict[str, Any]:
    """Return verified overview and per-endpoint status without changing router config."""
    api = QuRouterWebAPI.from_environment()
    api.login()
    sections: dict[str, dict[str, Any]] = {}
    try:
        for section in READ_ENDPOINTS:
            try:
                sections[section] = {"status": "ok", "data": _project_section(section, api.get(section))}
            except RouterAPIError as exc:
                sections[section] = {"status": "unavailable", "error": str(exc), "error_code": exc.error_code}
    finally:
        api.logout()
    available = sum(section["status"] == "ok" for section in sections.values())
    state = "ok" if available == len(sections) else "partial" if available else "unavailable"
    result = {"source": "qrouter_web_api", "status": state, "sections": sections,
              "transport": api.transport}
    if api.transport == "http_unencrypted":
        result["warning"] = "Credentials were sent over unencrypted HTTP; use HTTPS or a trusted isolated LAN"
    return result


def _project_section(section: str, data: Any) -> Any:
    """Keep the MCP result bounded to known status fields; omit site and client identity data."""
    if section == "overview":
        if not isinstance(data, dict):
            raise RouterAPIError("QuRouter overview response has an unexpected shape")
        return {key: data[key] for key in OVERVIEW_FIELDS if key in data}
    if section == "ports":
        if not isinstance(data, dict):
            raise RouterAPIError("QuRouter ports response has an unexpected shape")
        return {key: [{field: item[field] for field in PORT_FIELDS if field in item}
                      for item in data.get(key, []) if isinstance(item, dict)]
                for key in ("wan", "lan", "occupied") if isinstance(data.get(key), list)}
    if section == "wan":
        if not isinstance(data, dict):
            raise RouterAPIError("QuRouter WAN response has an unexpected shape")
        records = data.get("wan", [])
        if not isinstance(records, list):
            raise RouterAPIError("QuRouter WAN response has an unexpected shape")
        return {"wan": [{field: item[field] for field in WAN_FIELDS if field in item}
                         for item in records if isinstance(item, dict)]}
    raise RouterAPIError("Unsupported read-only QuRouter section")
