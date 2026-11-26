"""Read-only QHora SSH and Uptime Kuma collectors."""

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


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


def _ssh(command: str) -> str:
    host = os.environ.get("QROUTER_HOST", "")
    user = os.environ.get("QROUTER_USER", "")
    key = Path(os.environ.get("QROUTER_KEY_FILE", ""))
    known_hosts = Path(os.environ.get("QROUTER_KNOWN_HOSTS", ""))
    port = os.environ.get("QROUTER_PORT", "22")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]+", host) or not re.fullmatch(r"[A-Za-z0-9_.-]+", user):
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
    mem = next((line.split() for line in raw["memory"].splitlines() if line.split()[:1] == ["Mem:"]), None)
    if not mem or len(mem) < 4:
        raise CollectorError("Could not parse free output")
    interfaces = [{"name": f[0], "state": f[1]} for line in raw["interfaces"].splitlines() if len(f := line.split()) >= 2]
    radios, current = [], None
    for line in raw["wifi"].splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "Interface":
            current = {"interface": fields[1]}
            radios.append(current)
        if current:
            for i, word in enumerate(fields):
                if word == "channel" and i + 1 < len(fields):
                    current["channel"] = int(fields[i + 1])
                if word.startswith("("):
                    try: current["frequency_mhz"] = int(word[1:])
                    except ValueError: pass
                if word == "width:" and i + 1 < len(fields):
                    current["width"] = fields[i + 1]
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
    return {"observed_at": datetime.now(timezone.utc).isoformat(), "uptime": raw["uptime"].strip(),
            "memory_kb": {"total": int(mem[1]), "used": int(mem[2]), "free": int(mem[3])},
            "interfaces": interfaces, "wifi": radios, "listeners": listeners, "filesystems": filesystems,
            "mounts": raw["mounts"].splitlines(), "limitations": ["iptables is unavailable to the admin SSH account"]}


def router_read(section: str) -> dict:
    commands = {"interfaces": "interfaces", "addresses": "addresses", "routes": "routes",
                "neighbors": "neighbors", "wifi": "wifi", "listeners": "listeners", "filesystems": "filesystems"}
    if section not in commands:
        raise CollectorError("Unknown read-only router section")
    name = commands[section]
    output = _ssh(SSH_COMMANDS[name])
    if name == "interfaces":
        data = [{"name": f[0], "state": f[1]} for line in output.splitlines() if len(f := line.split()) >= 2]
    elif name == "addresses":
        data = [{"interface": f[0], "state": f[1], "addresses": f[2:]} for line in output.splitlines() if len(f := line.split()) >= 2]
    elif name == "neighbors":
        data = [{"address": f[0], "interface": f[f.index("dev") + 1] if "dev" in f else None,
                 "state": f[-1], "mac": f[f.index("lladdr") + 1] if "lladdr" in f else None}
                for line in output.splitlines() if len(f := line.split()) >= 2]
    elif name == "listeners":
        data = [line.split() for line in output.splitlines()]
    elif name == "filesystems":
        data = [line.split() for line in output.splitlines()]
    else:
        data = output.splitlines()
    return {"section": section, "observed_at": datetime.now(timezone.utc).isoformat(), "data": data}


def kuma_status() -> dict:
    base = os.environ.get("KUMA_BASE_URL", "").rstrip("/")
    slug = os.environ.get("KUMA_STATUS_SLUG", "")
    if not base.startswith(("http://", "https://")) or not re.fullmatch(r"[A-Za-z0-9_-]+", slug):
        raise CollectorError("Set KUMA_BASE_URL and a valid KUMA_STATUS_SLUG")
    result = {}
    for key, path in (("page", f"/api/status-page/{slug}"), ("heartbeat", f"/api/status-page/heartbeat/{slug}")):
        request = urllib.request.Request(base + path, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                result[key] = json.loads(response.read(1024 * 1024))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise CollectorError(f"Uptime Kuma {key} request failed: {exc}") from exc
    result["observed_at"] = datetime.now(timezone.utc).isoformat()
    return result
