# Software Design (SD)

## 1. Scope

This document describes the current implementation of QHora-CLI. It covers the Python CLI, stdio MCP server, QuRouter Web API collector, SSH collector, and Uptime Kuma Status Page collector. It does not define router configuration or any write-capable control plane.

## 2. Runtime and package

- Python `>=3.11`.
- Runtime modules use only the standard library.
- Optional installed command: `qurouter` (`qrouter_cli.cli:main`).
- Source invocation: `python -m qrouter_cli.cli ...`.
- MCP invocation: `python -m qrouter_cli.mcp_server`.
- SSH mode requires an OpenSSH `ssh` executable on `PATH`.

## 3. Module design

### `qrouter_cli/cli.py`

Parses two command groups:

- `router`: `status`, `web-status`, `integrated-status`, and a fixed SSH section enum.
- `kuma`: `status` and `monitor --name <exact-name>`.

Results are UTF-8 JSON on stdout. Collector errors are JSON on stderr and return exit code 1. `web-status` does not depend on SSH or Kuma; `integrated-status` combines Web API and Kuma and does not depend on SSH.

### `qrouter_cli/mcp_server.py`

Implements the stdio MCP subset used by this project: `initialize`, `notifications/initialized`, `ping`, `tools/list`, and `tools/call`. The supported tool schemas reject unknown properties. The server writes protocol output to stdout and does not open an HTTP listener. Error results set `isError: true`.

The server currently declares protocol version `2024-11-05` and a fixed server version `0.1.0`. It handles JSON-RPC notifications without replies, rejects notifications carrying IDs, supports batch requests, reports parse errors, and validates request/params shapes. It is a small local implementation rather than the official MCP Python SDK; host compatibility should be checked when upgrading MCP protocol versions.

### `qrouter_cli/web_api.py`

`QuRouterWebAPI` owns one short-lived login session per collection:

1. Validate an absolute HTTP(S) base URL without embedded credentials, query, or fragment.
2. Require HTTPS unless `QROUTER_WEB_ALLOW_INSECURE_HTTP` is explicitly enabled.
3. Load a password from `QROUTER_WEB_PASSWORD` or `QROUTER_WEB_PASSWORD_FILE`.
4. Login with `force=false`; do not displace an active UI session.
5. Call only `READ_ENDPOINTS` entries and project known fields.
6. Logout in `finally` and clear the in-memory token.

Redirects are rejected. TLS certificate verification is enabled; `QROUTER_WEB_CA_FILE` adds a private CA. Response cap is 1 MiB; request timeout is 8 seconds per request. Current allowlisted endpoint set:

| Section | Method/path | Projected fields |
|---|---|---|
| Overview | `GET /v1/debugmode/information` | firmware, operation mode, CPU, memory, uptime, connection count and feature flags |
| Ports | `GET /v2/network/ports_status` | port name/state/rate/traffic and occupied interface names |
| WAN | `GET /v2/network/wan/status` | interface/link/address/gateway/DNS fields |

Overview projection deliberately drops `site`, WAN identity fields, and unrecognized fields. The collector does not call the clients or event-log endpoints.

### `qrouter_cli/collectors.py`

#### SSH

`SSH_COMMANDS` is the command allowlist. `router_status()` runs a bounded set of fixed read commands and normalizes selected output; `router_read(section)` maps a validated section string to one fixed command. SSH uses `BatchMode=yes`, `StrictHostKeyChecking=yes`, explicit identity and known-hosts paths, a 5-second connect timeout, a 10-second subprocess timeout per command, and a 256 KiB stdout cap.

#### Uptime Kuma

`_kuma_snapshot()` fetches the published page and heartbeat JSON, joining monitors by ID. `kuma_status()` serializes refreshes under a process-local lock and caches the normalized result. Defaults: 15-second TTL, 300-second maximum stale age, 5-second timeout per HTTP request, and 1 MiB response cap per endpoint. Environment values are clamped to bounded ranges.

`kuma_monitor_status()` performs exact-name matching against the cached snapshot. Duplicate names return multiple matches rather than silently choosing one.

#### Integrated status

`integrated_router_status()` calls Web API and an exact Kuma monitor, `QuRouter Web` by default. `QROUTER_KUMA_MONITOR_NAME` overrides that name. Each source has its own status. Missing Kuma or Web API data yields `partial` when the other source is available, and `unavailable` only when both sources are unavailable.

## 4. MCP tools and schemas

| Tool | Input schema | Data source |
|---|---|---|
| `qrouter_web_status` | no properties | QuRouter Web API |
| `qrouter_integrated_status` | no properties | QuRouter Web API + exact Kuma monitor `QuRouter Web` |
| `qrouter_router_status` | no properties | SSH summary |
| `qrouter_router_read` | `{section}` enum: `interfaces`, `addresses`, `routes`, `neighbors`, `wifi`, `listeners`, `filesystems` | One SSH section |
| `qrouter_kuma_status` | no properties | Configured Kuma published page |
| `qrouter_kuma_monitor` | `{monitor_name}` string, 1–120 chars | Exact-name lookup on configured Kuma page |

No tool accepts a command string, arbitrary endpoint, HTTP method, router setting, or monitor mutation.

## 5. Configuration contract

### QuRouter Web API

| Variable | Required | Description |
|---|---:|---|
| `QROUTER_WEB_BASE_URL` | Yes | Explicit router API base, e.g. `https://192.168.100.1/miro/api`; no default is used |
| `QROUTER_WEB_USERNAME` | Yes | Local QuRouter account; default is `admin` for compatibility |
| `QROUTER_WEB_PASSWORD_FILE` | Yes, unless password env set | UTF-8 password file; strongly preferred, protected by host ACLs |
| `QROUTER_WEB_PASSWORD` | Alternative | Process environment secret; discouraged because privileged processes may inspect it |
| `QROUTER_WEB_CA_FILE` | No | Additional trusted CA PEM |
| `QROUTER_WEB_ALLOW_INSECURE_HTTP` | No | Must be `1`, `true`, or `yes` to allow HTTP |

### SSH

| Variable | Required | Description |
|---|---:|---|
| `QROUTER_HOST` | Yes | Router IP or hostname |
| `QROUTER_PORT` | No | SSH port; default `22` |
| `QROUTER_USER` | Yes | SSH account |
| `QROUTER_KEY_FILE` | Yes | Private key path |
| `QROUTER_KNOWN_HOSTS` | Yes | Pinned host-key database |
| `QROUTER_INCLUDE_RAW_ON_PARSE_ERROR` | No | Opt-in raw parsing excerpt, at most 10 lines × 200 characters; may contain network identifiers |

### Uptime Kuma

| Variable | Required | Description |
|---|---:|---|
| `KUMA_BASE_URL` | Yes | Kuma origin, including optional reverse-proxy base path |
| `KUMA_STATUS_SLUG` | Yes | Published Status Page slug |
| `KUMA_CACHE_TTL` | No | Cache lifetime in seconds; default 15, bounded 1–300 |
| `KUMA_STALE_MAX_AGE` | No | Maximum stale snapshot age in seconds; default 300, bounded 1–3600 |
| `QROUTER_KUMA_MONITOR_NAME` | No | Exact monitor selected by integrated status; default `QuRouter Web` |

### Logging

| Variable | Required | Description |
|---|---:|---|
| `QROUTER_LOG_LEVEL` | No | Structured JSON stderr logs: `DEBUG`, `INFO`, `WARNING`, or `ERROR`; off by default; allowlisted metadata only |

The sources are configured independently. Do not create placeholder credentials or empty config for unused sources.

## 6. Result and error semantics

- Kuma collection status `ok` means the status page API was read successfully; each monitor independently reports `up`, `down`, `pending`, `maintenance`, or `unknown`.
- Kuma `stale` means a refresh failed and the last successful snapshot is within the stale window.
- QuRouter Web API is summarized by section. A successful login does not make a failed section healthy.
- `partial` means some integration sources/sections worked and others did not.
- `unavailable` means no usable current or permitted stale data is available.
- Numeric firmware error codes are preserved; raw HTTP bodies are not returned.

## 7. Verification

Unit tests use Python `unittest` and local fixtures/mocks. They cover authentication flags, session handling, URL/transport validation, data projection, Kuma normalization/cache fallback, tool discovery, dispatch and argument rejection.

```powershell
python -m unittest discover -v
python -m compileall -q qrouter_cli tests
```

Live verification is optional and should use read-only endpoints on a trusted management network. Do not store device credentials in fixtures, logs, command history, MCP messages, or commits.
