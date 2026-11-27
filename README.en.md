# QHora-CLI

[繁體中文](README.md)

QHora-CLI is a read-only command-line interface and stdio MCP server for QHora-301W routers. It combines the QuRouter Web API, a fixed set of SSH diagnostics, and Uptime Kuma's published Status Page API. Run it on a trusted management host or NAS; do not install it into router firmware.

## Features and limitations

| Source | Capability | Requirements and current limitations |
|---|---|---|
| QuRouter Web API | Overview, firmware, CPU, memory, uptime, and per-section Ports/WAN results | Logs in, calls fixed endpoints, and logs out. On tested firmware 2.7.2.121, Ports/WAN return HTTP 519 and API error `-2`; these sections are reported unavailable rather than guessed |
| SSH | Uptime, memory, interfaces, addresses, routes, neighbors, Wi-Fi, listeners, filesystems, and mounts | Requires OpenSSH, a key, and pinned `known_hosts`. The `admin` account cannot read iptables |
| Uptime Kuma | Published Status Page groups, monitor states, latency, and check time | Requires no Kuma admin credentials or SSH; reads the published page and never creates or edits monitors |
| Third-party API status | Availability of third-party HTTP APIs monitored by Kuma | Kuma monitors report health; they are not a general-purpose live API proxy |

The project has no arbitrary shell, arbitrary URL fetch, router configuration changes, reboot operation, or Kuma administration tools. QuRouter login always uses `force=false`, so it will not replace an existing management session.

## Quick start

Requirements: Python 3.11 or later. The CLI and MCP runtime use the Python standard library; SSH mode additionally needs the system OpenSSH client.

```powershell
cd E:\QHora-CLI
python -m qrouter_cli.cli --help
```

Optionally install the command-line entry point:

```powershell
python -m pip install -e .
qurouter --help
```

### Web API only: no Kuma and no SSH

This is the minimum-dependency mode. It needs only a QuRouter Web API account and a password file. Do not set any `KUMA_*` or `QROUTER_HOST`/SSH variables.

```powershell
$env:QROUTER_WEB_BASE_URL = "https://192.168.100.1/miro/api"
$env:QROUTER_WEB_USERNAME = "monitor"
$env:QROUTER_WEB_PASSWORD_FILE = "C:\secrets\qhora_web_password"
$env:QROUTER_WEB_CA_FILE = "C:\secrets\qhora_ca.pem"
python -m qrouter_cli.cli router web-status
```

The command reports each API section separately. If some firmware endpoints fail while others work, the overall status is `partial`. The MCP equivalent is `qrouter_web_status`.

### Read Uptime Kuma

Kuma must be installed and have a published Status Page. This collector needs neither Kuma admin credentials nor SSH.

```powershell
$env:KUMA_BASE_URL = "http://uptime-kuma:3001"
$env:KUMA_STATUS_SLUG = "home-network"
python -m qrouter_cli.cli kuma status
python -m qrouter_cli.cli kuma monitor --name "QuRouter Web"
```

The default cache TTL is 15 seconds. If Kuma is unavailable, the collector can return the last successful snapshot marked `stale` within the configured stale limit. Set `KUMA_CACHE_TTL` (1–300 seconds) and `KUMA_STALE_MAX_AGE` (1–3600 seconds) to adjust these limits.

### SSH diagnostics

SSH accepts only key authentication through the system OpenSSH client and a pinned host key. Create a least-privilege account, a trusted `known_hosts` entry, and a dedicated private key first.

```powershell
$env:QROUTER_HOST = "192.168.100.1"
$env:QROUTER_PORT = "22200"
$env:QROUTER_USER = "monitor"
$env:QROUTER_KEY_FILE = "C:\secrets\qhora_ed25519"
$env:QROUTER_KNOWN_HOSTS = "C:\secrets\known_hosts"
python -m qrouter_cli.cli router status
python -m qrouter_cli.cli router interfaces
python -m qrouter_cli.cli router wifi
```

Run `python -m qrouter_cli.cli router --help` for all sections. Commands are fixed in an allowlist; callers cannot supply a remote command.

## CLI commands

```text
qurouter router web-status
qurouter router integrated-status
qurouter router status
qurouter router interfaces|addresses|routes|neighbors|wifi|listeners|filesystems
qurouter kuma status
qurouter kuma monitor --name "QuRouter Web"
```

`router integrated-status` combines the QuRouter Web API with Kuma's `QuRouter Web` heartbeat. Use `router web-status` when Kuma is not configured. `router status` and `router <section>` use SSH.

## MCP server

The stdio JSON-RPC server exposes these read-only tools:

| Tool | Dependency | Purpose |
|---|---|---|
| `qrouter_web_status` | QuRouter Web credentials | Read router Overview, Ports, and WAN APIs directly |
| `qrouter_integrated_status` | QuRouter Web credentials + Kuma Status Page | Cross-check the Web API with the `QuRouter Web` heartbeat |
| `qrouter_router_status` | SSH key + pinned host key | Collect a summary using fixed diagnostic commands |
| `qrouter_router_read` | SSH key + pinned host key | Read one allowlisted diagnostic section |
| `qrouter_kuma_status` | Kuma Status Page | List monitor states |
| `qrouter_kuma_monitor` | Kuma Status Page | Filter by an exact monitor name |

Example host configuration for Web API only (no Kuma or SSH):

```json
{
  "mcpServers": {
    "qhora-web-only": {
      "command": "uv",
      "args": ["run", "--directory", "E:/QHora-CLI", "python", "-m", "qrouter_cli.mcp_server"],
      "env": {
        "QROUTER_WEB_BASE_URL": "https://192.168.100.1/miro/api",
        "QROUTER_WEB_USERNAME": "monitor",
        "QROUTER_WEB_PASSWORD_FILE": "C:/secrets/qhora_web_password",
        "QROUTER_WEB_CA_FILE": "C:/secrets/qhora_ca.pem"
      }
    }
  }
}
```

Configure only the sources you use. Do not put passwords, API tokens, or private keys directly in the MCP configuration file.

## Security and transport

The QuRouter API sends its login password as Base64; Base64 is encoding, not encryption. HTTP is rejected by default. HTTPS certificates are verified, and `QROUTER_WEB_CA_FILE` can specify a private CA. Enable HTTP only on a trusted, isolated management LAN with `QROUTER_WEB_ALLOW_INSECURE_HTTP=1`; credentials are then sent in clear text. If the router's HTTPS certificate is untrusted, install/trust the correct CA instead of disabling validation.

`QROUTER_WEB_BASE_URL` must be set explicitly; the client has no implicit HTTP URL. Prefer `QROUTER_WEB_PASSWORD_FILE` protected by OS ACLs or a secret manager. Avoid `QROUTER_WEB_PASSWORD`: environment variables may be visible to privileged local processes. Optional JSON logs go to stderr when `QROUTER_LOG_LEVEL` is set to `DEBUG`, `INFO`, `WARNING`, or `ERROR`; logging is off by default and includes only allowlisted metadata. Integrated status looks for the Kuma monitor `QuRouter Web` by default; override it with `QROUTER_KUMA_MONITOR_NAME`. Raw SSH parse diagnostics are off by default. Setting `QROUTER_INCLUDE_RAW_ON_PARSE_ERROR=1` includes at most 10 lines of 200 characters each and may reveal SSIDs, IP addresses, or MAC addresses.

See the [Security Policy](SECURITY.md) and [security design](docs/SECURITY.md).

## Documentation

- [Product architecture](docs/PRODUCT_ARCHITECTURE.md)
- [Software Design (SD)](docs/SD.md)
- [Security design](docs/SECURITY.md)
- [Traditional Chinese README](README.md)

## Development and verification

```powershell
python -m unittest discover -v
python -m compileall -q qrouter_cli tests
```

Start the MCP stdio server with `python -m qrouter_cli.mcp_server`. The CLI/MCP tools do not change router or Kuma configuration; Web API login/logout create and clear a short-lived session.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
