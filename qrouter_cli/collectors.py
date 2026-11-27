"""Read-only QHora SSH and Uptime Kuma collectors."""

import json
import ipaddress
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .web_api import RouterAPIError, router_web_status

SSH_COMMANDS = {
    "uptime": "uptime",
    "memory": "free",
    "interfaces": "PATH=/usr/bin:/bin:/sbin:/usr/sbin /sbin/ip -br link",
    "addresses": "PATH=/usr/bin:/bin:/sbin:/usr/sbin /sbin/ip -br addr",
    "routes": "PATH=/usr/bin:/bin:/sbin:/usr/sbin /sbin/ip route show",
    "neighbors": "PATH=/usr/bin:/bin:/sbin:/usr/sbin /sbin/ip neigh show",
    "wifi": "PATH=/usr/bin:/bin:/sbin:/usr/sbin /usr/bin/iw dev",
    "listeners": "PATH=/usr/bin:/bin:/sbin:/usr/sbin /sbin/ss -H -lntu",
    "filesystems": "PATH=/usr/bin:/bin:/sbin:/usr/sbin /bin/df -kP",
    "mounts": "PATH=/usr/bin:/bin:/sbin:/usr/sbin /usr/bin/findmnt -n -o TARGET,FSTYPE,OPTIONS",
}


class CollectorError(RuntimeError):
    pass


def _parse_free(output: str) -> dict | None:
    for line in output.splitlines():
        fields = line.split()
        if fields and fields[0].lower().rstrip(":") == "mem" and len(fields) >= 4:
            try:
                values = [int(item.replace(",", "")) for item in fields[1:4]]
                return dict(zip(("total", "used", "free"), values))
            except ValueError:
                return None
    return None


def _parse_wifi(output: str) -> list[dict]:
    radios, current = [], None
    for line in output.splitlines():
        match = re.match(r"^\s*Interface\s+(\S+)", line)
        if match:
            current = {"interface": match.group(1)}
            radios.append(current)
            continue
        if current is None:
            continue
        for pattern, key, convert in (
            (r"\bchannel\s+(\d+)", "channel", int),
            (r"\((\d+)\s*MHz\)", "frequency_mhz", int),
            (r"\bwidth:\s*([^\s]+(?:\s+MHz)?)", "width", str),
            (r"\bssid\s+(.+?)\s*$", "ssid", str),
            (r"\btxpower\s+([\d.]+)\s*dBm", "txpower_dbm", float),
        ):
            found = re.search(pattern, line, re.IGNORECASE)
            if found:
                try:
                    current[key] = convert(found.group(1))
                except ValueError:
                    continue
    return radios


def _parse_neighbors(output: str) -> list[dict]:
    states = {"REACHABLE", "STALE", "DELAY", "PROBE", "FAILED", "INCOMPLETE", "PERMANENT", "NOARP"}
    result = []
    for line in output.splitlines():
        fields = line.split()
        if not fields:
            continue
        row = {"address": fields[0], "interface": None, "state": None, "mac": None}
        for idx, field in enumerate(fields[:-1]):
            if field == "dev": row["interface"] = fields[idx + 1]
            elif field == "lladdr": row["mac"] = fields[idx + 1]
        row["state"] = next((field for field in reversed(fields) if field.upper() in states), fields[-1] if len(fields) > 1 and fields[-2] != "lladdr" else None)
        result.append(row)
    return result


def _parse_diagnostics(section: str, output: str) -> dict:
    if os.environ.get("QROUTER_INCLUDE_RAW_ON_PARSE_ERROR", "").lower() not in ("1", "true", "yes"):
        return {}
    lines = output.splitlines()[:10]
    return {section: [line[:200] for line in lines]}


def _valid_ssh_host(host: str) -> bool:
    if not host or len(host) > 253 or "%" in host or host.startswith("[") or host.endswith("]"):
        return False
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    if all(char in "0123456789." for char in host):
        return False
    labels = host.rstrip(".").split(".")
    return all(0 < len(label) <= 63 and re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?", label) for label in labels)


def _ssh(command: str) -> str:
    host = os.environ.get("QROUTER_HOST", "")
    user = os.environ.get("QROUTER_USER", "")
    key = Path(os.environ.get("QROUTER_KEY_FILE", ""))
    known_hosts = Path(os.environ.get("QROUTER_KNOWN_HOSTS", ""))
    port = os.environ.get("QROUTER_PORT", "22")
    if not _valid_ssh_host(host) or not re.fullmatch(r"[A-Za-z0-9_.-]+", user):
        raise CollectorError("Set valid QROUTER_HOST and QROUTER_USER values")
    if not key.is_file() or not known_hosts.is_file():
        raise CollectorError("SSH key and pinned known_hosts files are required")
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise CollectorError("QROUTER_PORT must be between 1 and 65535")
    argv = ["ssh", "-F", "NUL" if os.name == "nt" else "/dev/null", "-o", "BatchMode=yes",
            "-o", "StrictHostKeyChecking=yes", "-o", f"UserKnownHostsFile={known_hosts}",
            "-o", "ConnectTimeout=5", "-i", str(key), "-p", port, f"{user}@{host}", command]
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectorError(f"SSH query failed: {exc}") from exc
    if result.returncode:
        raise CollectorError("SSH query failed: " + result.stderr.strip()[:300])
    if len(result.stdout) > 256 * 1024:
        raise CollectorError("SSH output exceeded 256 KiB")
    return result.stdout


def router_status() -> dict:
    raw = {name: _ssh(command) for name, command in SSH_COMMANDS.items()}
    memory = _parse_free(raw["memory"])
    warnings = []
    diagnostics = {}
    if memory is None:
        warnings.append("Could not parse free output")
        diagnostics.update(_parse_diagnostics("memory", raw["memory"]))
    interfaces = [{"name": f[0], "state": f[1]} for line in raw["interfaces"].splitlines() if len(f := line.split()) >= 2]
    radios = _parse_wifi(raw["wifi"])
    if raw["wifi"].strip() and not radios:
        warnings.append("Could not parse iw dev output")
        diagnostics.update(_parse_diagnostics("wifi", raw["wifi"]))
    listeners = {"tcp": 0, "udp": 0}
    for line in raw["listeners"].splitlines():
        proto = line.split(maxsplit=1)[0].lower() if line.split() else ""
        if proto.startswith("tcp"): listeners["tcp"] += 1
        if proto.startswith("udp"): listeners["udp"] += 1
    filesystems = []
    for line in raw["filesystems"].splitlines()[1:]:
        f = line.split()
        if len(f) >= 6:
            try: filesystems.append({"mount": f[-1], "size_kb": int(f[1]), "used_kb": int(f[2]), "available_kb": int(f[3])})
            except ValueError: continue
    result = {"observed_at": datetime.now(timezone.utc).isoformat(), "uptime": raw["uptime"].strip(),
            "memory_kb": memory,
            "interfaces": interfaces, "wifi": radios, "listeners": listeners, "filesystems": filesystems,
            "mounts": raw["mounts"].splitlines(), "limitations": ["iptables is unavailable to the admin SSH account"]}
    if warnings: result["parse_warnings"] = warnings
    if diagnostics: result["parse_diagnostics"] = diagnostics
    return result


def router_read(section: str) -> dict:
    commands = {"interfaces": "interfaces", "addresses": "addresses", "routes": "routes",
                "neighbors": "neighbors", "wifi": "wifi", "listeners": "listeners", "filesystems": "filesystems"}
    if not isinstance(section, str) or section not in commands:
        raise CollectorError("Unknown read-only router section")
    name = commands[section]
    output = _ssh(SSH_COMMANDS[name])
    if name == "interfaces":
        data = [{"name": f[0], "state": f[1]} for line in output.splitlines() if len(f := line.split()) >= 2]
    elif name == "addresses":
        data = [{"interface": f[0], "state": f[1], "addresses": f[2:]} for line in output.splitlines() if len(f := line.split()) >= 2]
    elif name == "neighbors":
        data = _parse_neighbors(output)
    elif name == "wifi":
        data = _parse_wifi(output)
    elif name == "listeners":
        data = [line.split() for line in output.splitlines()]
    elif name == "filesystems":
        data = [line.split() for line in output.splitlines()]
    else:
        data = output.splitlines()
    result = {"section": section, "observed_at": datetime.now(timezone.utc).isoformat(), "data": data}
    known_neighbor_states = {"REACHABLE", "STALE", "DELAY", "PROBE", "FAILED", "INCOMPLETE", "PERMANENT", "NOARP"}
    parse_failed = (name == "neighbors" and bool(output.strip()) and any(row["state"] is None or row["state"].upper() not in known_neighbor_states for row in data)) or (name == "wifi" and bool(output.strip()) and not data)
    if parse_failed:
        result["parse_warnings"] = [f"Some {name} output could not be fully parsed"]
        diagnostics = _parse_diagnostics(name, output)
        if diagnostics:
            result["parse_diagnostics"] = diagnostics
    return result


_KUMA_LOCK = threading.Lock()
_KUMA_CACHE: dict | None = None
_KUMA_CACHE_AT = 0.0


def _bounded_int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise CollectorError(f"{name} must be an integer") from exc
    return max(minimum, min(value, maximum))


def _http_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise CollectorError("Uptime Kuma response exceeded 1 MiB")
        result = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise CollectorError(f"Uptime Kuma returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CollectorError("Uptime Kuma request failed or timed out") from exc
    except json.JSONDecodeError as exc:
        raise CollectorError("Uptime Kuma returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise CollectorError("Uptime Kuma returned an unexpected response")
    return result


def _kuma_snapshot() -> dict:
    base = os.environ.get("KUMA_BASE_URL", "").rstrip("/")
    slug = os.environ.get("KUMA_STATUS_SLUG", "")
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
        raise CollectorError("Set KUMA_BASE_URL and a valid KUMA_STATUS_SLUG")
    page = _http_json(base + f"/api/status-page/{slug}")
    heartbeat = _http_json(base + f"/api/status-page/heartbeat/{slug}")
    heartbeat_list = heartbeat.get("heartbeatList") or {}
    status_names = {0: "down", 1: "up", 2: "pending", 3: "maintenance"}
    monitors = []
    for group in page.get("publicGroupList") or []:
        if not isinstance(group, dict):
            continue
        for monitor in group.get("monitorList") or []:
            if not isinstance(monitor, dict) or monitor.get("id") is None:
                continue
            points = heartbeat_list.get(str(monitor["id"])) or []
            latest = points[-1] if points else {}
            status_code = latest.get("status") if isinstance(latest, dict) else None
            monitors.append({
                "id": monitor["id"], "group": group.get("name"), "name": monitor.get("name"),
                "type": monitor.get("type"), "status": status_names.get(status_code, "unknown"),
                "ping_ms": latest.get("ping") if isinstance(latest, dict) else None,
                "checked_at": latest.get("time") if isinstance(latest, dict) else None,
            })
    return {"source": "uptime_kuma_status_page", "status": "ok", "slug": slug,
            "title": (page.get("config") or {}).get("title"), "monitors": monitors,
            "observed_at": datetime.now(timezone.utc).isoformat()}


def kuma_status(force_refresh: bool = False) -> dict:
    global _KUMA_CACHE, _KUMA_CACHE_AT
    ttl = _bounded_int_env("KUMA_CACHE_TTL", 15, 1, 300)
    stale_limit = max(ttl, _bounded_int_env("KUMA_STALE_MAX_AGE", 300, 1, 3600))
    with _KUMA_LOCK:
        age = time.monotonic() - _KUMA_CACHE_AT
        if _KUMA_CACHE is not None and age < ttl and not force_refresh:
            return {**_KUMA_CACHE, "cache_age_seconds": round(age, 1)}
        try:
            snapshot = _kuma_snapshot()
        except CollectorError:
            if _KUMA_CACHE is not None and age <= stale_limit:
                return {**_KUMA_CACHE, "status": "stale", "cache_age_seconds": round(age, 1),
                        "warning": "Uptime Kuma refresh failed; showing last successful status-page snapshot"}
            raise
        _KUMA_CACHE = snapshot
        _KUMA_CACHE_AT = time.monotonic()
        return {**snapshot, "cache_age_seconds": 0}


def kuma_monitor_status(monitor_name: str) -> dict:
    if not isinstance(monitor_name, str) or not monitor_name.strip() or len(monitor_name) > 120:
        raise CollectorError("monitor_name must be a non-empty exact monitor name")
    snapshot = kuma_status()
    matches = [monitor for monitor in snapshot["monitors"] if monitor.get("name") == monitor_name]
    if not matches:
        raise CollectorError("No monitor with that exact name exists on the configured Kuma status page")
    return {"source": snapshot["source"], "status": snapshot["status"], "monitor_name": monitor_name,
            "matches": matches, "cache_age_seconds": snapshot.get("cache_age_seconds", 0),
            "observed_at": snapshot["observed_at"], "warning": snapshot.get("warning")}


def integrated_router_status() -> dict:
    """Cross-check direct QuRouter Web API data with its Kuma availability monitor."""
    try:
        web = router_web_status()
    except RouterAPIError as exc:
        web = {"source": "qrouter_web_api", "status": "unavailable", "error": str(exc)}
    try:
        monitor_name = os.environ.get("QROUTER_KUMA_MONITOR_NAME", "QuRouter Web").strip() or "QuRouter Web"
        kuma = kuma_monitor_status(monitor_name)
    except CollectorError as exc:
        kuma = {"source": "uptime_kuma_status_page", "status": "unavailable", "error": str(exc)}
    states = (web["status"], kuma["status"])
    status = "ok" if all(state == "ok" for state in states) else "unavailable" if all(state == "unavailable" for state in states) else "partial"
    return {"source": "qhora_web_api_and_uptime_kuma", "status": status,
            "qurouter_web_api": web, "uptime_kuma_qurouter_web": kuma,
            "observed_at": datetime.now(timezone.utc).isoformat()}
